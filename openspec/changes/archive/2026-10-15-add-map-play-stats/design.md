# Design

## Context

Motivation and scope are in `proposal.md`; the requirements are in `specs/player-stats` and
`specs/map-control`. This change is a read-side feature: nothing new is recorded.

How the relevant parts work today:

- **What is already stored.** `matches` has one row per match with `map`, `gametype`,
  `started_at`, `duration` and `finished` (1 ran to its limit, 0 cut short by a map change
  or clean stop, NULL no report yet or a crash). `match_players` has one row per player per
  match with `frags`, `deaths` and the rest, and `players.is_bot` marks bots.
- **Where frags come from.** `match_players.frags` is incremented from the live `:kill`
  events, so it is counted for cut-short and crashed matches too. The report's per-weapon
  frags live in `weapon_stats` and are not used here, so nothing double counts.
- **The store.** `PlayerStore` is one SQLite connection on one worker thread, serialised by
  an asyncio lock. `Ops` holds the queries, `transact(fn, write=False)` runs a read, and
  `revision` is bumped by each committed write. Schema changes are forward-only
  migrations keyed by `SCHEMA_VERSION`.
- **Availability.** `runtime.recorder.enabled` is false when the store could not be
  opened. The players API answers 503 `players_unavailable` in that case; the map list
  must not.
- **The Maps screen.** `GET /api/maps` is built from the in-memory catalogue and shared by
  `MapCard` and `MapTable`. There is no sorting. The gametype filter is a `useState`; view
  and favourites-only are persisted with `useStoredChoice`. The Players section already has
  `PlayerDialog`, built on `Dialog` and `useResource`.

## Goals / Non-Goals

**Goals:**

- One set of per-map numbers that both views, the sort, the filter and the dialog read, so
  they cannot disagree.
- The map list keeps working, unchanged in shape, when history is off or broken.
- No new recording and no change to the player totals.

**Non-Goals:**

- A cached per-map totals table (see D3).
- Server-side sorting or filtering of maps; the whole list is already in the browser.
- Time played per map.

## Decisions

### D1. Definitions

For a map name `M`, over rows in `matches` with `map = M`:

- **played** = matches with `finished = 1` that have at least one `match_players` row.
- **frags** = `SUM(match_players.frags)` over every match on `M`, finished or not, for
  every player, bots included.
- **cut short** = matches with `finished = 0` that have at least one `match_players` row.
- **last played** / **first played** = `MAX` / `MIN` of `started_at` over every match on
  `M` that has at least one `match_players` row, whatever its `finished` value.

"Played" is finished matches only so that it agrees with the per-player `matches` total on
the Players screen, and so a map skipped by a vote does not look popular. The dialog shows
the cut-short count so those matches are visible. Requiring a participant keeps a match on
an empty server from inflating a count. Frags are taken from every match because they were
really scored; this also matches the player totals, which sum `frags` over all matches.

*Alternatives:* counting every match (rewards skipped maps); counting only matches with a
human (needs a join to `players` for every count and hides bot-only play that the frag
total includes).

### D2. The list carries the totals; the dialog has its own endpoint

`MapModel` gains `played: int | null`, `frags: int | null` and `last_played: int | null`.
`GET /api/maps` runs one grouped query (`Ops.map_totals()`) and merges the result into the
catalogue entries by name. A map with no history gets `0, 0, null`. When the recorder is not
enabled, or the query raises `PlayerStoreError`, all three are `null` for every map, the
failure is logged at warning level once per outage, and the response is still 200.

The detail view is `GET /api/maps/{name}/stats` (`MapStatsModel`): 404 `map_not_found` for
a map the catalogue does not list, 503 `players_unavailable` when history is off, as the
players API does. It is a second route rather than more fields on the list because the top
fraggers and per-gametype rows would multiply the list's size by every installed map for
data that is only read for one.

*Alternative:* a separate `GET /api/maps/stats` merged client side. Rejected: two requests
on every Maps load, a second failure mode, and a window in which the two views could show
different things.

### D3. Aggregate on read, with an index; no cache table

The list query is a single `GROUP BY m.map` over `matches` joined to a per-match sum of
`match_players`. An index `matches_map ON matches(map)` is added in schema v2. The players
list needed a cache table (`player_totals`) because it is read for tens of thousands of
players and sorted by every column; the map list is one pass over the match history and is
read when the Maps section opens.

A cache (`map_totals`, refreshed with `refresh_totals` in the same transaction) stays the
fallback if the measured query time on a large history is a problem. Acceptable is under
roughly 50 ms at 100,000 `match_players` rows; the task list includes measuring it.

*Measured* (task 1.4): a generated database of 100,000 `match_players` rows over 5,000
matches and 150 maps; `map_totals` took about 21-23 ms (median of 10 runs) and
`map_detail` for one map about 2 ms. That is under the 50 ms line, so no cache table was
added.

*Alternative:* a materialised table from the start. Rejected for now: it would have to be
kept in step on `apply_report` and `add_counters`, which is a bigger change to the
recording path than this change should risk.

### D4. Schema v2

`SCHEMA_VERSION` becomes 2 and `_MIGRATIONS[1]` creates the index. Nothing else changes in
the schema, so the migration is cheap and idempotent. The existing newer-schema guard makes
a downgrade refuse to open the file instead of misreading it.

### D5. Sorting and filtering are client-side and shared

The sort and the played filter are state in `Maps.tsx`, applied to the same `maps` array
before the existing gametype and favourites filters feed either view, so cards and table
cannot order or filter differently. Sort choice and played filter are persisted with
`useStoredChoice` (keys `xonotic-webui.maps.sort` and `xonotic-webui.maps.played`). The
filter chain is gametype, favourites, played; sorting is last. A comparator ties on name.
"Recently played" puts maps with no `last_played` last.

When the totals are `null` the three stat-dependent sort options and the played filter are
disabled and the stored choice is treated as Name and All without being overwritten, so a
temporary outage does not lose the operator's preference.

A single "Sort by" control is used rather than clickable table headings because the card
view has no headings. Heading clicks can set the same state later.

### D6. The dialog

`MapDialog` is built on `Dialog` and loads `/api/maps/{name}/stats` with `useResource`
when opened, as `PlayerDialog` does. The map title becomes a button in `MapCard` and in
`MapTable`. The top fraggers are buttons that open `PlayerDialog` from the same section
state, so only one dialog is open at a time. Fraggers are shown with `ColoredText` and a
"bot" badge. The list is the top ten; there is no paging.

Opening the dialog does not poll. It shows what was true when it opened.

### D7. Freshness

The Maps section fetches `/api/maps` when it opens and after its own actions, as now. The
totals are not live: a match that finishes while the page is open shows on the next load or
reload. This is deliberate; the Players section polls because it is a live scoreboard, and
map totals change at most once per match.

## Risks / Trade-offs

- **Aggregate cost grows with history** → one indexed grouped query on every Maps load;
  measured in the tasks; D3 names the cache table as the fallback.
- **The query shares the store's single worker** → a slow aggregate delays recorder writes
  queued behind it. Mitigation: it is one statement over indexed columns, and recording
  already tolerates delay (the recorder keeps events in memory and flushes every couple of
  seconds, retrying a failed flush). Measured together with D3.
- **Map name mismatch** → totals are matched by exact name between `matches.map` and the
  catalogue name; a map whose recorded name differs in case would show zero. Both come
  from the game's own map name, so this is not expected; a task verifies it with the
  recorder fixtures.
- **Played excludes cut-short matches** → a map that is usually skipped can show 0 played
  and many frags. That is the intended reading and the dialog shows the cut-short count.
- **Bots inflate frag totals on bot-heavy servers** → intentional and consistent with the
  top fraggers list (D1); the bot badge makes it visible there.
- **Stale numbers on an open page** → accepted (D7).

## Migration Plan

1. Deploy the panel. On first start the player database is migrated from v1 to v2 in one
   transaction (index creation); an empty or very large database both complete quickly.
2. No data is rewritten and no configuration is added.
3. Rollback: a panel older than this change refuses to open the v2 file. Drop the index and
   set `PRAGMA user_version = 1` by hand to go back; no data is lost either way.
