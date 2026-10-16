# Design

## Context

Motivation and scope are in `proposal.md`. The requirements are in `specs/match-history` and
`specs/player-stats`.

How the relevant parts work today:

- **What is stored per match.** `matches` has one row per match: `match_id` (the game's
  id), `map`, `gametype`, `started_at`, `duration` and `finished`. `finished` is 1 when the
  match ran to its limit, 0 when it was cut short, and NULL when there is no report yet or
  the server crashed. `match_players` has one row per player per match:
  - the live counters `frags`, `deaths`, `suicides` and `teamkills`
  - from the report: `score`, `kills`, `alivetime`, `dmg`, `dmgtaken`, `wins`, `rank`,
    `avglatency`, `scoreboard_valid` and `reported`

  Scoreboard labels without a column of their own (captures and other gametype labels) go
  to `extra_stats`. `players.is_bot` marks bots.
- **When a match row appears.** The recorder writes a match only once it has something to
  write: a live counter (a frag, death, suicide or team kill) or a report. A human who
  idles through a match appears only through the report.
- **The report.** `ReportParser` already reads each player's team (`t`) and the
  `Q team#N` headers. It drops the `e` lines that follow a `Q` header, which carry the
  team's scores. Each player's `scoreboard-*` / `total-*` events hold every scoreboard value
  the game showed, but the game only writes non-zero values. `scoreboardvalid` and
  `scoreboardpos` are written only for clients on the final board when the report is
  printed. The report is printed for finished matches and for cut-short ones (on
  `changelevel` or a clean stop), not for crashes.
- **Matches played today.** `player_totals.matches` counts rows with `finished = 1 AND
  scoreboard_valid = 1`. This already implements the rule the specs now state; nothing in
  the count changes.
- **Store and API patterns.** `PlayerStore` is one SQLite connection on one worker thread.
  `revision` is bumped by every committed write, and the players list uses it in an ETag
  that the browser polls with `If-None-Match` (`usePlayers`). Schema changes are
  forward-only migrations keyed by `SCHEMA_VERSION` (currently 2). When the store is not
  open, `runtime.recorder.enabled` is false and the players API answers 503
  `players_unavailable`.
- **The live scoreboard.** The dashboard renders `Scoreboard.tsx` from `MatchScoreboardModel`:
  columns, players with a `values` map, and teams.

## Goals / Non-Goals

**Goals:**

- One source for a past match's scoreboard (the report) that covers finished and cut-short
  matches in the same way.
- The history dialog looks like the dashboard scoreboard and shares its table code.
- Older matches stay readable with whatever they recorded, with no backfill.
- No change to how the player totals are computed.

**Non-Goals:**

- Keeping the game's column order and sort marks per match (see D3).
- Spectators in a past match.
- A cache table for the match list (see D6).

## Decisions

### D1. Verify the report before building on it

The repo has no captured report for a team game, a player who left mid-match, or a player
spectating at the end. The definitions in the specs depend on three behaviours:

- A leaver's figures appear in the report without `scoreboardvalid`.
- A player spectating at the end has no `scoreboardvalid`.
- The `e` lines after `Q team#N` carry the team's `scoreboard-*` values.

The first task captures these from a real 0.8.6 server on the test LXC (10.0.1.147), in
the same way as the existing fixtures:

- `report_tdm_finished.txt`
- `report_ctf_finished.txt`
- `report_leaver.txt`
- `report_spectator_at_end.txt`

If any behaviour differs, the specs and this design are revised before the code is written.

**Findings (captured 2026-10-16 from the unmodified 0.8.6 dedicated server and headless
clients; the fixtures are in `tests/fixtures/xonotic/`).** All three assumptions held:

- **A leaver's figures appear without `scoreboardvalid`.** In `report_leaver.txt` the player
  who left (`:part:` before the end) has `joins`, `avglatency`, `alivetime` and their
  `scoreboard-*` values, and no `scoreboardvalid`, `scoreboardpos`, `rank` or `matches`.
  The player who stayed and the one who joined late, in the slot the leaver freed (a new
  player id on the same ent), both have `scoreboardvalid`, `scoreboardpos` and `matches`.
- **A player spectating at the end has no `scoreboardvalid`.** In
  `report_spectator_at_end.txt` they have `rank`, `joins` and `alivetime`, but no
  `scoreboardvalid`, `scoreboardpos` or `matches`. `rank` is therefore not a sign of being
  on the board. The game's own `:player:` dump marks them with the team `spectator`.
- **`Q team#N` is followed by the team's `scoreboard-*` values.** Both `Q` headers come
  before the first `P` line. A team with a score of 0 has no `e` lines at all (red in
  `report_tdm_finished.txt`). Team values use `scoreboard-` only, never `total-`. A CTF
  team has `scoreboard-caps` and `scoreboard-score`.

Other things the captures showed, which the design already allows for:

- A deathmatch report has no `t` line. A team game's players have `t 5` (red) or `t 14`
  (blue).
- In `tdm`, `wins 1` is on every member of the winning team and on nobody else. The CTF
  capture, ended by `endmatch` with one capture each, has no `wins` on anyone, so it
  doubles as the draw case for D5's winner rule.
- `scoreboardpos` is unique per player on the final board (1 to the number of players on
  it).

### D2. Schema v3

`_MIGRATIONS[2]`:

```sql
ALTER TABLE match_players ADD COLUMN team INTEGER;          -- report `t`
ALTER TABLE match_players ADD COLUMN board_pos INTEGER;     -- report `scoreboardpos`
ALTER TABLE match_players ADD COLUMN name TEXT;             -- name used in this match
ALTER TABLE matches ADD COLUMN board_kept INTEGER NOT NULL DEFAULT 0;
ALTER TABLE matches ADD COLUMN humans INTEGER NOT NULL DEFAULT 0;   -- see D6
ALTER TABLE matches ADD COLUMN bots INTEGER NOT NULL DEFAULT 0;
-- then: UPDATE matches SET humans = ..., bots = ... counted from match_players
CREATE TABLE match_scores (
    match_pk  INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    label     TEXT NOT NULL,
    value     REAL NOT NULL,
    PRIMARY KEY (match_pk, player_id, label)
);
CREATE TABLE match_teams (
    match_pk  INTEGER NOT NULL,
    team      INTEGER NOT NULL,
    label     TEXT NOT NULL,
    value     REAL NOT NULL,
    PRIMARY KEY (match_pk, team, label)
);
CREATE INDEX matches_started ON matches(started_at);
```

- `match_scores` holds every scoreboard label from the report (via the existing
  `scoreboard()` helper) except `elo` and `rounds_pl`, which the game hides.
- `match_teams` holds the team scores from the `Q` blocks.
- `apply_report` sets `board_kept = 1`. This lets the dialog tell a v3 match from an older
  one without guessing from empty tables.
- Existing rows are not rewritten, except that the migration fills in `matches.humans` and
  `matches.bots` for the matches already stored (D6). The `extra_stats` and `match_players`
  columns that the totals read are still written as now, so no totals query changes.
  `match_scores` partly duplicates them, which keeps the history independent of how the
  totals are stored.

*Alternatives:*

- Values as more columns on `match_players`: rejected. Gametypes add their own labels, and
  the live board already handles labels without knowing the gametype.
- A JSON blob per match: rejected. The player-filter query and future per-label queries
  would need to parse it.

### D3. Scoreboard columns and order

- **Order of players.** For a match with `board_kept`, players with `board_pos` come first,
  in that order: this is the game's own final order. Players without `board_pos` (not
  playing at the end) follow, by score and then name. For every other match, players are
  ordered by frags, then name.
- **Columns.** Always `score`, `kills`, `deaths`, `suicides`. Then any other label that is
  non-zero for someone in the match: first the labels the live board already knows (in
  `board.py` `LABELS` order), then the rest alphabetically. Display names come from
  `LABELS`, as on the live board. A label the game reports as zero for everyone is left
  out; for the base four, a missing value shows as 0.
- **Primary column.** `score` is marked primary. No column is marked lower-is-better,
  because the order is already the game's.

*Alternative:* store the `:labels:player:` line from the game's end-of-match `:scores`
dump. That would give the exact column set and sort marks, but the dump is only printed for
finished matches, so cut-short matches would still need this fallback. The recorder would
also have to tie a dump to the report that follows it. Rejected: two code paths, little
gain, since `board_pos` already gives the order.

### D4. Values for matches without a kept board

| match kind | values shown |
| --- | --- |
| v3 with a report (`board_kept = 1`) | `match_scores` |
| older, reported | `score`, `kills`, `dmg`, `dmgtaken` from `match_players`, `deaths`, `suicides`, `teamkills` from the live counters, plus `extra_stats` |
| no report (crash, or in progress) | the live counters, with `frags` shown as `kills` |

Teams and team totals appear only for `board_kept` matches. The name shown is
`match_players.name`, or the player's current name when it is NULL. Ping and time are
`avglatency` and `alivetime` when reported, and blank otherwise.

### D5. Outcome, tag and winner are derived on read

- **Outcome**:
  - `finished` for `finished = 1` and `cut_short` for `finished = 0`
  - for NULL (no report so far): `in_progress` when the match's `match_id` is the
    recorder's current match, and `no_report` otherwise

  A match that has its report is finished (or cut short) even while it is still the
  recorder's current match, which is the case between the end of the match and the next
  `:gamestart:`.

  The recorder gains a read-only `current_match_id`.
- **Humans and bots**: the `humans` and `bots` counts of the match's `match_players` rows
  (by `players.is_bot`), kept on `matches` (D6). Listed when humans ≥ 1. **vs bots** when
  humans = 1 and bots ≥ 1.
- **Winner**, for finished matches only:
  - in a team game (any `team` set), the team of the players with `wins = 1`, with the
    team colour from `board.py` `TEAM_COLORS`
  - otherwise the player with `wins = 1`
  - none when no player has `wins = 1`, as in a draw

  For older team matches, where team is unknown, the winner is every player with
  `wins = 1`. The list shows the first and a count ("^1Ace +2").

The outcome, the tag and the winner are not stored, so matches recorded before this change
get them too. The counts are stored (D6) and filled in for older matches by the migration.

*Alternative:* count on read, with a grouped read over `match_players`. Tried first and
rejected by the measurement in D6.

### D6. List query and paging

`Ops.list_matches(map, gametype, player_id, hide_vs_bots, limit, offset)` works in three
steps:

1. `matches` is filtered by `humans >= 1` and the given filters, and ordered by
   `started_at DESC, id DESC`.
2. The page is cut with `LIMIT` and `OFFSET`.
3. Only the page's rows get their winner, with a second query keyed by the page's ids.

The total count uses the same filters. The `player_id` filter is an `EXISTS` on
`match_players`.

**Counters on `matches`.** The first version counted humans and bots on read, with a grouped
read over `match_players`. Measured on a generated database of 5,000 matches and 100,000
`match_players` rows (a page of 50 plus the count, median of 7 runs), that took about 59 ms
with no filter or with one of map, gametype or hide-vs-bots, and about 79 ms with the player
filter. That is over the 50 ms target, so the fallback this section named was adopted:

- `matches.humans` and `matches.bots` are written with the rows. The first time a player
  gets a `match_players` row in a match (from a live counter or a report), the match's
  count for their kind goes up by one. A later write for the same player changes nothing.
- The migration fills them in for matches already stored, so older matches are listed and
  tagged too.

Measured the same way after the change: about 1.5 ms with no filter, 1.0 to 1.4 ms with
map, gametype or hide-vs-bots, and 7 ms with the player filter. One match's details read
took 0.7 ms.

### D7. API

New router `api/history.py`:

- **`GET /api/matches`** takes `map`, `gametype`, `player` (int), `vs_bots` (bool, default
  true; false hides vs-bots matches), `limit` (default 50, maximum 200) and `offset`. It
  returns `{revision, total, matches: [MatchSummary]}`.
  - The ETag is `"<revision>-<current_match_id>-<query hash>"`, so a crash that turns
    "in progress" into "no report" without a database write still changes it.
  - `MatchSummary` has `id`, `started_at`, `map`, `gametype`, `duration`, `outcome`,
    `humans`, `bots`, `vs_bots` and `winner`. `winner` is either
    `{kind: "team", team, color}` or `{kind: "player", player_id, name, plain_name, is_bot, others}`.
- **`GET /api/matches/{id}`** returns a `MatchSummary` plus `scoreboard`, shaped like the
  live `MatchScoreboardModel` so `Scoreboard`'s table can render it:
  - `columns`, `teams`, `players`
  - each player has `values`, `team`, `ping` and `time_s`, plus `player_id` and
    `at_end: bool | null`
  - no `spectators` or `available`: the table that renders it takes columns, players and
    teams, and spectators are out of scope
  - `board_kept` tells the dialog whether teams can be shown

  `at_end` is null for no-report and in-progress matches.
- Errors: 404 `match_not_found`, and 503 `players_unavailable`, as in the players router.

`id` is the database primary key, not the game's match id. It is shorter and the game's id
is never shown.

### D8. Recording changes

- `ReportParser._event` stores `e` lines under a `Q` header in `Report.teams`
  (`{team: {label: value}}`) using the same `scoreboard()` reduction.
- `ReportedPlayer` gains `team`, `board_pos`, `name` and `scores`.
- `_reported()` fills them:
  - `team` from `ReportPlayer.team`
  - `board_pos` from `scoreboardpos`
  - `name` from the report's `n`, or else the participant's current name
  - `scores` from `scoreboard()` minus the hidden labels
- `apply_report` writes:
  - the new `match_players` columns
  - `match_scores`, replaced per player like `weapon_stats`
  - `match_teams`, replaced per match
  - `matches.board_kept = 1`
- `add_counters` sets `match_players.name` to the participant's current name when it
  writes a row. A report later overwrites it.
- `_PlanReport` carries the team scores.

Applying the same report twice still changes nothing.

### D9. Frontend

- **Shared table.** `Scoreboard.tsx` is split. A new `ScoreTable` gets columns, players and
  teams and renders the table and team rows. The dashboard's `Scoreboard` keeps its panel,
  its "no one connected" text and the spectators line around it. In history mode,
  `ScoreTable` also shows a "not at end" badge for `at_end === false` and makes names
  buttons that open `PlayerDialog`.
- **`sections/Matches.tsx`** has a table of start time (`formatEpoch`), map, gametype,
  duration, outcome badge, players ("1 + 3 bots"), winner (with `ColoredText`, or a team
  swatch) and a vs-bots badge. Pager as in Players.
  - Filters: a map select and a gametype select, both built from the installed maps and
    gametypes already loaded elsewhere, and a "hide vs bots" checkbox.
  - The filters and page live in the URL query (`?map=&gametype=&player=&vs_bots=0&page=`),
    so the player dialog link and a reload both work. A `player` filter shows as a
    removable chip with the player's name.
- **`useMatches`** polls like `usePlayers`, with `If-None-Match`, keeping the query.
- **`MatchDialog`** is built on `Dialog` and `useResource`. It shows the summary line,
  then `ScoreTable`. For older matches it adds a note that teams were not recorded. Opening
  a player closes it and opens `PlayerDialog`, as `MapDialog` does.
- **`PlayerDialog`** gets a "Matches played" line, keeps "Wins N", and adds a
  "View matches" link to `/matches?player=<id>`.
- **Navigation** gets a Matches entry after Players.

## Risks / Trade-offs

- **The report differs from the assumptions** (leavers, spectators, team `e` lines) → D1
  captures real reports first and revises before building.
- **A short visit does not register** → a human who joins, never frags or dies, and leaves
  before the report has no row. A one-human match can then still be tagged vs bots.
  Accepted: they took no part in the score. Stated in `docs/guide.md`.
- **List cost grows with history** → the first version was too slow at 5,000 matches, so
  `matches` keeps its human and bot counts (D6). The list is then an indexed read of `matches`
  and a page's worth of winners.
- **The single store worker** → the list and detail reads queue behind recorder writes and
  the reverse. Each is a handful of indexed statements, and recording already tolerates
  delay.
- **Older team matches look like free-for-all** → accepted. The dialog says teams were not
  recorded for that match.
- **Storage growth** → about 10 to 20 `match_scores` rows per player per match. A busy
  server with 10,000 matches of 8 players adds about a million small rows, a few tens of MB.
  Accepted, since history is kept indefinitely by spec. Pruning is a future change.
- **The winner in a draw** → no player or team has `wins = 1`, so there is no winner. Shown
  as "–".

## Migration Plan

1. Deploy the panel. On first start the player database migrates from v2 to v3 in one
   transaction: three `ADD COLUMN`s on `match_players`, three on `matches`, two tables and
   one index, then one `UPDATE` that fills in each match's `humans` and `bots`. No other
   rows are rewritten.
2. Matches recorded before the upgrade show as described in D4. Matches from then on keep
   full boards.
3. Rollback: an older panel refuses the v3 file through the newer-schema guard. To go back
   by hand, drop `match_scores`, `match_teams` and `matches_started`, then set
   `PRAGMA user_version = 2`. The added columns are ignored by v2 code, and SQLite allows
   them to stay.
