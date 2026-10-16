# Proposal

## Why

The panel already records every match: its map, gametype, length and how it ended, plus
each player's frags and end-of-match figures. But nothing shows a match as a match. An
operator cannot look back at last night's games, see who won a CTF on `boil` or check how a
match ended. The player totals also leave a gap. The Players table has a **Matches**
column, but nothing says what it counts, and the details dialog only shows it inside the
wins line. This change adds a match history and states what "matches played" means.

## What Changes

- **A Matches section.** A new navigation entry listing matches newest first, a page at a
  time. Each row shows when the match started, map, gametype, duration, how it ended
  (finished, cut short, in progress, no report), the number of humans and bots, the winner,
  and a **vs bots** tag. Filters: map, gametype, and hide vs bots. The list refreshes on
  its own when a match ends.
- **A match details dialog.** It shows the final scoreboard: each player's scoreboard
  values in the game's board order, with ping and time playing. Team games group players
  under their team's totals. Players who left before the end, or were spectating when it
  ended, are listed and marked "not at end". Names are the ones used in that match.
- **What is listed.** Every match with at least one human taken part is listed. Matches
  with only bots, or nobody, are not.
- **vs bots tag.** A match is tagged **vs bots** when exactly one human and at least one
  bot took part. It is worked out from what is already stored, so matches recorded before
  this change are tagged too. vs-bots matches count toward player totals like any other.
- **More of the end-of-match report is kept** (player database schema v3), for matches
  from now on:
  - each player's team, board position, every scoreboard value, and the name they used
  - each team's scores

  Older matches show their players without team grouping, under their current names.
- **Matches played, defined.** A match counts toward a player's matches played (and can
  count as a win) only when it ran to its limit and the player was on the final scoreboard
  at its end. A player who joined late counts. A player who left early, or whose match was
  cut short, does not. This is what the panel already counts; the spec now says so.
- **Player dialog.** It gains a **Matches played** line and a link to the Matches section
  filtered to that player.
- **New endpoints**: `GET /api/matches` (filtered, paged, with an ETag) and
  `GET /api/matches/{id}`.

Out of scope:

- deleting or editing recorded matches
- per-match weapon or achievement breakdowns in the dialog
- rebuilding team data for matches recorded before schema v3
- showing spectators in a past match
- counting vs-bots matches separately in player totals
- sorting the list by anything other than start time

## Capabilities

### New Capabilities

- `match-history`: the record of each past match and its final scoreboard, how a match's
  outcome and vs-bots tag are decided, the list and details API, and the Matches section
  with its details dialog.

### Modified Capabilities

- `player-stats`: defines when a match counts toward a player's matches played and wins.
  The end-of-match record gains team, board position, scoreboard values and the name used.
  The player dialog shows matches played and links to that player's matches.

## Impact

- **Backend**:
  - `src/xonotic_webui/players/report.py` keeps team scores from `Q` blocks.
  - `src/xonotic_webui/players/recorder.py` passes team, board position, scoreboard values
    and the name used to the store, and exposes the match currently being played.
  - `src/xonotic_webui/players/store.py` gets the schema v3 migration, the writes for the
    new data, and the list and detail queries.
  - New `src/xonotic_webui/api/history.py` router and models in
    `src/xonotic_webui/api/schemas.py`.
  - `web/openapi.json` and `web/src/api/schema.d.ts` are regenerated.
- **Frontend**:
  - a new `web/src/sections/Matches.tsx` and `/matches` route in `web/src/sections.tsx`
  - a new `MatchDialog` component
  - the scoreboard table in `Scoreboard.tsx` is split out so the dashboard and the dialog
    share it
  - `PlayerDialog.tsx` gets the matches-played line and link; `styles.css` gets the new
    styles
- **Fixtures**: new end-of-match reports captured from a real 0.8.6 server: a team game,
  a player leaving mid-match, and a player spectating at the end.
- **State**: the player database is migrated in place to v3 on first start. Downgrading to
  a panel that predates v3 is refused by the existing newer-schema guard.
- **Dependencies**: none.
- **Docs**: `docs/guide.md` gets a Matches section and the definition of matches played.
