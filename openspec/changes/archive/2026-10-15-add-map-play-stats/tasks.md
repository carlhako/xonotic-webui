# Tasks

Run the groups in order; each depends on the ones before it. Design decisions are cited as
D1–D7 (`design.md`). Backend tests go in `tests/`, frontend tests in `web/src/test/`.

## 1. Store: per-map totals and detail (player-stats)

- [x] 1.1 Add schema v2 in `src/xonotic_webui/players/store.py`: `SCHEMA_VERSION = 2` and `_MIGRATIONS[1]` creating `matches_map ON matches(map)` (D4); verify `tests/test_player_store.py` cases for a fresh database at v2, a v1 database with data migrated in place with every row intact, and a database newer than v2 still refused
- [x] 1.2 Add `Ops.map_totals()` returning `{map: (played, frags, last_played)}` per D1 and a `PlayerStore.map_totals()` read wrapper; verify tests for a finished match, a cut-short match (frags counted, not played, counts as last played), a bot's frags, a finished match with no participant, a map with only unreported matches, and two maps not mixing
- [x] 1.3 Add `Ops.map_detail(name)` and the store wrapper: played, cut short, frags, first and last played, finished matches per gametype (unrecorded gametype grouped as unknown), and the ten top fraggers with `player_id`, `name`, `frags`, `is_bot`, ordered by frags then name (D1); verify tests for ordering and the name tie-break, a bot in the list, more than ten players cut to ten, an empty map giving zeros and empty lists, and a player's frags summed across several matches
- [x] 1.4 Measure `map_totals` on a generated database of about 100,000 `match_players` rows and record the time in `design.md` D3; if it exceeds about 50 ms, add the `map_totals` cache table refreshed in the same transactions as `player_totals` and re-verify; verify the figure is written down

## 2. API (map-control, player-stats)

- [x] 2.1 Add `played`, `frags` and `last_played` (all nullable) to `MapModel`, and make `GET /api/maps` merge `map_totals()` by map name, giving `0, 0, null` to maps with no history and `null, null, null` for every map when the recorder is disabled or the store raises `PlayerStoreError` (D2); verify `tests/test_api_maps.py` cases for totals present, a never-played map, history disabled still returning 200 with the full list, and a store error still returning 200
- [x] 2.2 Add `MapStatsModel` and `GET /api/maps/{name}/stats` with 404 `map_not_found` for a map not in the catalogue and 503 `players_unavailable` when history is off (D2); verify API tests for a played map, a never-played map giving zeros, an unknown map, history off, and a map with a name needing URL encoding
- [x] 2.3 Regenerate `web/openapi.json` and `web/src/api/schema.d.ts` with `scripts/export_openapi.py` and the web client generator; verify `tests/test_openapi_snapshot.py` passes and `npm --prefix web run build` type-checks
- [x] 2.4 Verify the recorder's map name matches the catalogue's with an end-to-end case in `tests/test_player_recorder_e2e.py` (or `tests/test_api_maps.py`): play a match on a fixture map through the recorder and read its totals back through `GET /api/maps` (design risk "map name mismatch")

## 3. Maps section: totals, sort and filter (map-control)

- [x] 3.1 Add the API client types and a `lib/mapTotals` helper for number formatting (thousands separators, dash for `null`); verify a unit test for 0, 1,380 and `null`
- [x] 3.2 Show the totals in both views: a `Played 42× · 1,380 frags` line in `MapCard` and **Played** and **Frags** right-aligned columns in `MapTable`, both with a dash when `null` (D5); verify tests in `web/src/test/maps.test.tsx` that card and row show identical figures for the same map, that a never-played map shows 0, and that `null` shows dashes in both
- [x] 3.3 Add the shared "Sort by" control (Name, Most played, Most frags, Recently played) in `Maps.tsx`, persisted with `useStoredChoice` under `xonotic-webui.maps.sort`, with the name tie-break and never-played maps last for Recently played (D5); verify tests for each ordering in both views, ties by name, and the choice surviving a remount
- [x] 3.4 Add the Played / Never played filter persisted under `xonotic-webui.maps.played`, chained after the gametype and favourites filters, with a "no maps match" message when nothing is left; verify tests for each choice, combining with favourites only and with a gametype, and the empty message
- [x] 3.5 Disable the stat-dependent sort choices and the played filter when the totals are `null`, treating the stored choice as Name and All without overwriting it; verify a test that the stored choice is restored once totals return
- [x] 3.6 Style the totals line, columns and the new controls in `web/src/styles.css`, including 375 px; verify with `npm --prefix web run build` and a check in the browser pane at 375 px

## 4. Map details dialog (map-control)

- [x] 4.1 Add `api.mapStats(name)` and the `MapDialog` component on `Dialog` and `useResource`: matches played and cut short, frags, first and last played (using `formatEpoch`), the per-gametype list, and the top fraggers with `ColoredText` and a bot badge; verify tests for a played map, a never-played map showing the "not been played yet" message, a failed load showing the error, and history off showing "player history is not being recorded"
- [x] 4.2 Make the map title a button in `MapCard` and `MapTable` that opens the dialog, returning focus to it on close; verify tests for opening from each view, Escape and the close control closing it, and that the view, sort and filters are unchanged afterwards
- [x] 4.3 Make each top fragger open `PlayerDialog` by id from the same section state so only one dialog is open at once; verify a test that activating a fragger shows that player's dialog and the map dialog is closed
- [x] 4.4 Style the dialog for 375 px without horizontal page scrolling; verify with `npm --prefix web run build` and a check in the browser pane at 375 px

## 5. Docs and integration

- [x] 5.1 Update the README Maps section for the Played and Frags figures, what "played" counts, Sort by, the played filter and the details dialog; verify `tests/test_readme.py` passes and every route named matches the code
- [x] 5.2 Run the full suites: `pytest`, `ruff check`, `npm --prefix web run test` and `npm --prefix web run build`; verify all pass
- [x] 5.3 End-to-end in the browser pane against the fake server: play and finish a match, see the map's Played and Frags change after a reload in both views, sort by most played, filter to never played, open the dialog and a top fragger, then stop recording and confirm the list shows dashes with the sort options disabled; verify each step behaves as the specs state

## Workflow follow-up

- Archive the change after review, syncing the delta specs into `openspec/specs/`.
