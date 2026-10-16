# Tasks

Run the groups in order. Each depends on the ones before it. Design decisions are cited as
D1–D9 (`design.md`). Backend tests go in `tests/`, frontend tests in `web/src/test/`.

## 1. Capture real reports (D1)

- [x] 1.1 On the test LXC (10.0.1.147, real 0.8.6), capture four end-of-match reports in
  the same way as the existing fixtures (`g_playerstats_gamereport_uri -`, headless
  client):
  - a finished `tdm` match
  - a finished `ctf` match
  - a `dm` match a human leaves before the limit
  - a `dm` match where a human moves to spectating before the limit

  Add them as `tests/fixtures/xonotic/report_tdm_finished.txt`, `report_ctf_finished.txt`,
  `report_leaver.txt` and `report_spectator_at_end.txt`, with rows in
  `tests/fixtures/xonotic/README.md`. Verify each file holds one complete report block
  that `fake_report` can replay.
- [x] 1.2 Check the captures against D1's three assumptions:
  - the leaver has figures but no `scoreboardvalid`
  - the spectator has no `scoreboardvalid`
  - `Q team#N` is followed by the team's `scoreboard-*` values

  Write the findings under D1 in `design.md`. If any assumption fails, stop and revise the
  specs and design with the user before group 2. Verify the findings are written down.

## 2. Report parsing (player-stats, match-history)

- [x] 2.1 Make `ReportParser` keep the `e` lines after a `Q` header in
  `Report.teams: dict[int, dict[str, float]]`, reduced with `scoreboard()` (D8). Verify
  new `tests/test_player_parsers.py` cases against the tdm and ctf fixtures give each
  team's score, and existing parser tests still pass.
- [x] 2.2 Extend `ReportedPlayer` and `_reported()` with `team`, `board_pos` (from
  `scoreboardpos`), `name` and `scores` (every scoreboard label except `elo` and
  `rounds_pl`) (D8). Verify unit tests:
  - the ctf fixture gives captures in `scores`
  - the leaver fixture gives `board_pos` None and `scoreboard_valid` False
  - the opted-out fixture's player has no report name

## 3. Store: schema v3 and writes (match-history)

- [x] 3.1 Add schema v3 in `src/xonotic_webui/players/store.py`: `SCHEMA_VERSION = 3` and
  `_MIGRATIONS[2]` as in D2. Verify `tests/test_player_store.py` cases:
  - a fresh database at v3
  - a v2 database with data migrated in place, every row intact, and `board_kept = 0`
  - a database newer than v3 still refused
- [x] 3.2 Make `apply_report` write `team`, `board_pos` and `name` on `match_players`,
  replace the player's `match_scores` rows and the match's `match_teams` rows, and set
  `board_kept = 1`. Give it the team scores as a new argument (D8). Verify store tests:
  - applying the same report twice leaves identical rows
  - `player_totals` is unchanged from before this change for the same input
- [x] 3.3 Make `add_counters` set `match_players.name` from a new `name` argument, and make
  the recorder pass the participant's current name in `_PlanCounter` and the team scores in
  `_PlanReport` (D8). Verify `tests/test_player_recorder.py` cases:
  - a rename mid-match records the later name
  - a report's name overwrites the counter's name
- [x] 3.4 Add `PlayerRecorder.current_match_id` (read-only, None when no match or the
  server is not running) (D5). Verify recorder tests that it follows `:gamestart:` and
  clears on stop.
- [x] 3.5 Verify the matches-played rule end to end in `tests/test_player_recorder_e2e.py`.
  Replay the leaver, spectator, finished and unfinished fixtures, then check:
  - only players on the final board of a finished match gain a match
  - a late joiner gains one
  - a vs-bots match counts

  This covers the new player-stats requirement.

## 4. Store: reads (match-history)

- [x] 4.1 Add `Ops.list_matches(map, gametype, player_id, hide_vs_bots, limit, offset)`
  returning `(total, rows)` with outcome inputs, human and bot counts, `vs_bots` and winner
  (D5, D6), and a `PlayerStore` wrapper. Verify store tests:
  - bots-only and empty matches are not listed
  - newest first
  - each filter alone and combined
  - the player filter includes a match they left
  - the vs-bots tag for 1+bots, 2 humans and 1 alone
  - the winner for dm, tdm, a draw and an older team match
  - paging and total
- [x] 4.2 Add `Ops.get_match(id)` returning the summary and the scoreboard rows with the
  values source, order and columns of D3 and D4. Verify store tests:
  - a v3 finished dm in board order with "not at end" players after
  - a v3 tdm with teams
  - a ctf with extra columns
  - an older reported match
  - a no-report match from counters
  - a renamed player showing the match-time name
  - an unknown id giving None
- [x] 4.3 Measure `list_matches` (first page plus count, no filter and with each filter) on
  a generated database of about 5,000 matches and 100,000 `match_players` rows. Record the
  time under D6 in `design.md`. If it exceeds about 50 ms, add the counter columns D6 names
  and re-verify. Verify the figure is written down.

## 5. API (match-history)

- [x] 5.1 Add the `MatchSummary`, `MatchWinner`, `MatchList`, `MatchHistoryPlayer` and
  `MatchDetail` models in `api/schemas.py`. Add the `api/history.py` router with
  `GET /api/matches` (filters, paging, `limit` capped at 200, ETag per D7, 304) and
  `GET /api/matches/{id}` (404 `match_not_found`, 503 `players_unavailable`), and mount it.
  Verify new `tests/test_api_history.py` cases:
  - list and detail shapes
  - each filter
  - 304 on an unchanged ETag
  - the ETag changing when the current match id changes
  - `in_progress` while the recorder's current match is running
  - 404 and 503
- [x] 5.2 Regenerate `web/openapi.json` with `scripts/export_openapi.py` and
  `web/src/api/schema.d.ts` with `npm --prefix web run gen:api`. Verify
  `tests/test_openapi_snapshot.py` passes and `npm --prefix web run build` type-checks.

## 6. Shared scoreboard table (live-match unchanged)

- [x] 6.1 Split `Scoreboard.tsx` into `ScoreTable` (columns, players, teams, optional "not
  at end" badge and player activation) and the dashboard `Scoreboard` wrapper (D9). Verify
  the existing dashboard tests in `web/src/test/` pass unchanged and a new `ScoreTable` test
  covers the badge and the player button.

## 7. Matches section and dialog (match-history)

- [x] 7.1 Add API client types, `api.matches(query, etag)`, `api.match(id)` and a
  `useMatches` hook that polls with `If-None-Match` like `usePlayers`. Verify a hook test
  that a 304 keeps the rows and that a query change refetches.
- [x] 7.2 Add `sections/Matches.tsx` and the `/matches` route after Players in
  `sections.tsx`. It has the table, outcome badges, the players cell, the winner cell,
  the vs-bots badge and the pager, plus map, gametype and hide-vs-bots filters and a
  removable player chip, all kept in the URL query (D9). Verify `web/src/test/matches.test.tsx`
  cases:
  - newest first
  - the empty message
  - "player history is not being recorded" on 503
  - each filter updating the URL and the request
  - a reload with `?player=` applying the filter
  - paging
- [x] 7.3 Add `MatchDialog` on `Dialog` and `useResource`: the summary line, `ScoreTable`,
  the "teams were not recorded" note for older matches, and player activation that opens
  `PlayerDialog` with only one dialog open (D9). Verify tests:
  - opening from a row
  - Escape and the close control returning focus with filters intact
  - a team match grouped under team totals
  - a "not at end" player marked
  - opening a player
- [x] 7.4 Add the "Matches played" line and the "View matches" link to `/matches?player=<id>`
  in `PlayerDialog`. Verify `web/src/test/players.test.tsx` cases that the line shows the
  API's `matches` and that the link navigates with the filter applied.
- [x] 7.5 Style the section, badges and dialog in `web/src/styles.css`, within the 1280 px
  layout. Verify with `npm --prefix web run build` and a look in the browser pane.
- [x] 7.6 Document the Matches section in `docs/guide.md`:
  - what is listed
  - the outcomes and the vs-bots tag
  - the dialog and "not at end"
  - older matches lacking teams

  In the Players part, add when a match counts as played. Verify `tests/test_readme.py`
  passes and every route named matches the code.

## 8. Integration

- [x] 8.1 Run the full suites: `pytest`, `ruff check`, `npm --prefix web run test` and
  `npm --prefix web run build`. Verify all pass.
- [x] 8.2 End to end in the browser pane against the fake server, using `fake_report` with
  the new fixtures:
  1. Play and finish a dm with bots and see it appear tagged vs bots with its winner.
  2. Replay the tdm report and open it to see team totals.
  3. Replay the leaver report and see "not at end".
  4. Hide vs bots, filter by map, then open a player and use "View matches".
  5. Stop recording and see the unavailable message.

  Verify each step behaves as the specs state.
- [x] 8.3 On the test LXC with the real server, upgrade a panel holding a v2 database with
  history, then check:
  - old matches list and open without teams
  - a new tdm match shows teams
  - the Players **Matches** figures are unchanged by the upgrade

## Workflow follow-up

- Archive the change after review, syncing the delta specs into `openspec/specs/`.
