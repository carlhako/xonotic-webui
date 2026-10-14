# Tasks

Run the groups in order. Each depends on the ones before it. Design decisions are cited
as D1–D10 (`design.md`). "The spike" is the local 0.8.6 capture described under **Spike
findings** in `design.md`.

## 1. Real-server fixtures

- [x] 1.1 Capture these from a real 0.8.6 dedicated server and a headless SDL client, launched the way the fixtures README describes but with `g_playerstats_gamereport_uri -` and bots:
  - a `sv_cmd who "|"` reply with a human with a key and bots
  - `:kill:` lines for `frag`, `tk` (a team gametype), `suicide` and `accident`
  - a complete report block with a human who actually played, including a weapon, `wins` and `matches`
  - a report from a match cut short by `gotomap`
  - a map change with a human connected (re-joins with new ids)
  - a client disconnecting while the next map loads

  Save them under `tests/fixtures/xonotic/` as `who_reply.txt`, `kill_variants.txt`, `report_finished.txt`, `report_unfinished.txt`, `session_map_change_rejoin.txt` and `session_leave_during_map_change.txt`, and add each to the README table. Verify every file is raw server output with the leading `^7`, and record in `design.md` anything that contradicts the Spike findings, in particular whether a `:part` is logged for a client lost during a map change.
- [x] 1.2 Extend `tests/fake_xonotic/server.py` so tests can drive the new paths:
  - `fake_join` takes an optional fingerprint, and `who` replies in the captured format with `|` or space separators
  - `fake_kill <mode> <killer> <victim>` emits a `:kill:` line
  - `fake_report <fixture>` prints a captured report block
  - `fake_map` re-joins every rostered client with fresh ids, as the real server does

  Document the new commands in its docstring. Verify `tests/test_fake_server.py` cases for each new command.

## 2. Parsing (events, `who`, report)

- [x] 2.1 Add `PlayerKill(mode, killer_id, victim_id)` to `events.py` and have `parse_event` recognise `:kill:<mode>:<killer>:<victim>:...`, ignoring unknown modes. Verify tests in `tests/test_colors_events.py` against every line in `kill_variants.txt`, plus a malformed line returning `None`.
- [x] 2.2 Implement `WhoReplyCollector` in `players/who.py` (D2):
  - it starts at `List of client information`, ends at `Finished listing`, and splits rows on `|` taking fields from the right
  - an empty fingerprint, `null/botclient` or `hidden` means none

  Verify tests against `who_reply.txt`, a name containing `|`, a 20-character truncated name, an empty fingerprint, and that unrelated lines in between are not consumed.
- [x] 2.3 Implement the report recogniser and parser in `players/report.py` (D6):
  - a block starts at `V <n>` and ends at a blank line or a non-report line, which is passed through
  - the parsed result carries the header fields, and per `P` block the key, `i`, `n`, `t` and a dict of `e` events

  Verify tests against `report_finished.txt` and `report_unfinished.txt`, a block interrupted by an unrelated line, a stray `V 9` line followed by normal output, and `n` absent.

## 3. Line fan-out and the reserved report target

- [x] 3.1 Replace `Supervisor.set_line_sink` with `add_line_sink`: sinks are called in registration order and a raising sink is logged without stopping the others (D1). Move `StatusTracker` to it. Verify the existing status and supervisor tests pass, and a new test shows a raising first sink does not stop the second.
- [x] 3.2 Add `("g_playerstats_gamereport_uri", "-")` to `FORCED_CVARS` (D8). Verify:
  - the wrapper-config test shows it written last
  - a settings test shows a raw override of `g_playerstats_gamereport_uri` refused as reserved (server-settings delta scenario)
  - the cvar catalogue test shows it as reserved (regenerate `cvars.json`)
  - the curated "Report match statistics" toggle is removed from the registry: it would otherwise be a setting for a reserved cvar (server-settings delta, curated settings requirement)
- [x] 3.3 Add `Console.add_filter` for standing filters fed every output line before fan-out, with consumed lines added to the suppressed set (D7). Register a `StatsReportFilter` built on the 2.3 recogniser. Verify console tests (server-console delta scenario):
  - a report emitted by the fake server reaches no live client and is absent from replay
  - the `:end` and `:gameover` lines around it are delivered
  - a pending query's collector still sees lines first

## 4. Store (SQLite)

- [x] 4.1 Add `Settings.players_db` (`state_dir / "players.db"`) and `players/store.py` (D5):
  - schema version 1 via `PRAGMA user_version`, with forward-only migrations
  - WAL mode and a single connection used through `asyncio.to_thread` under a lock
  - the tables and indexes in D5

  Verify store tests: a fresh database is created at version 1, reopening keeps the data, a newer `user_version` refuses to open with a clear error, and no call blocks the event loop (each runs in the worker thread).
- [x] 4.2 Implement the store's write API, each write in one transaction:
  - get or create a player by key
  - upsert an alias
  - open, extend and close sessions, and close leftover open sessions at start-up from `last_seen`
  - upsert a match
  - add live counters to `match_players`
  - apply a parsed report: match columns, `weapon_stats`, `achievements` and `extra_stats`

  Verify unit tests for each, including applying the same report twice being idempotent.
- [x] 4.3 Implement the read API (D5, D9):
  - `list_players(sort, order, q, bots, limit, offset)` with a whitelisted sort column, `id` tiebreak, escaped `LIKE` over all aliases (colour-stripped, any case), `total`, K/D as `frags / max(deaths, 1)`, accuracy `null` with no shots, and open sessions counted up to now
  - `get_player(id)`

  Verify tests for every sort column in both orders, search matching an old alias, bots excluded and included, paging, zero deaths, no shots, an unknown id, and that a seeded 20,000-player database lists a page in under 100 ms.

## 5. Recorder

- [x] 5.1 Implement `players/recorder.py` participants and identity (D2):
  - a `:join` creates a participant keyed by match player id
  - humans are resolved by a batched `who` lookup about 100 ms after the last join, with the name key used if the lookup fails
  - bots get `bot:<name>`
  - `:name` records an alias

  Verify recorder tests with the fake server: a human with a key, the same key under a new name joining the same player, two keyless players named `Player`, `^1Ace` and `^4Ace` merging without a key, a lookup timeout falling back to the name, and one `who` query for a burst of re-joins.
- [x] 5.2 Count `:kill` events against participants: frag, death, suicide plus death, accident as a death only, team kill not a frag. Pending participants accumulate until resolved. Verify tests for each mode, a frag against a bot counting for the human, and kills arriving before the lookup completes being kept.
- [x] 5.3 Implement sessions across map changes (D3):
  - an *awaiting rejoin* mark on `:gamestart`, with the session continued when the same slot re-joins with the same key
  - closed on `:part`, on a different key, or when the 120 s grace lapses (at the gamestart time)
  - all closed on server stop or crash
  - leftovers closed at start-up

  Verify tests driven by `session_map_change_rejoin.txt` and `session_leave_during_map_change.txt`: one session across a map change, a session ended by a crash at the stop time, and a panel restart closing a leftover session at `last_seen`.
- [x] 5.4 Apply reports (D6):
  - match by `I`, else create the match from `M`/`G`/`I`
  - link players through `i` to the match's participants, including those who left
  - fall back to the fingerprint, then `n`, then skip with a log line
  - `finished` comes from `matches` and the win from `wins`
  - release the participant table afterwards

  Verify tests with the fixtures: a finished match records score, alivetime, damage, weapons, achievements and the win; a player who left mid-match still gets their row; a cut-short match is stored with `finished = 0` and no wins; a report for a match the panel did not see start is still stored.
- [x] 5.5 Add the write-behind flush (D4):
  - every 2 s, and immediately on `:gamestart`, after a report, on server stop and on shutdown
  - bumps `revision` on commit
  - store errors are logged and never propagate to the line sink or the supervisor

  Verify tests:
  - counters reach the database within one interval
  - a store raising on write leaves the game server running and the tracker's status unaffected (player-stats "Recording problems do not disturb the server")
  - shutdown flushes pending counts
- [x] 5.6 Wire `PlayerRecorder` into `Runtime`: register its line sink and state subscription, start the flush task in `startup()`, flush and close in `shutdown()`. Verify a runtime wiring test and an end-to-end test that runs the fake server through join, kills, a report and a stop, then reads the expected totals back from the store.

## 6. API

- [x] 6.1 Add the `PlayerRow`, `PlayerList` and `PlayerDetail` models to `api/schemas.py` and an `api/players.py` router with `GET /api/players` (query parameters and validation per D9, `ETag` and `304` on `If-None-Match`) and `GET /api/players/{id}` (`404 player_not_found`). Register it in `api/__init__.py`. Verify API tests:
  - default sort by frags descending
  - an invalid `sort` returns `422`
  - `limit` is capped
  - `q` matches an alias
  - `bots=false` hides bots
  - the 304 round trip
  - the detail has `key_prefix` of at most 8 characters and never the full fingerprint
  - no response contains an IP address
- [x] 6.2 Regenerate `web/openapi.json` and `web/src/api/schema.d.ts`. Verify `tests/test_openapi_snapshot.py` passes and `npm --prefix web run build` type-checks.

## 7. Web: Players section

- [x] 7.1 Add the `players` and `player` calls to `api/client.ts`, and `api/usePlayers.ts`:
  - polls every 5 s while the document is visible, sending `If-None-Match` and keeping current rows on a 304 or while loading
  - pauses when hidden

  Verify vitest cases with fake timers for the interval, the pause when hidden, the 304 keeping data, and a changed query refetching at once.
- [x] 7.2 Add `sections/Players.tsx` and register `/players` in `sections.tsx` (D10):
  - the table with every spec column, coloured names via `ColoredText`, durations as `18h 2m`, last seen relative with the local absolute time in `title`
  - sortable `<button>` headers with `aria-sort`, a second activation reversing
  - debounced search, a "show bots" toggle with a bot marker, paging with the total
  - an empty state
  - view state kept in the URL query

  Verify `players.test.tsx`:
  - default frags-descending order
  - sort and reverse
  - sort applied server-side across pages (the request carries `sort`)
  - search and bots toggle requests
  - the empty state
  - state surviving a refresh tick
  - a deep link to `/players?sort=time_playing` restoring the view
- [x] 7.3 Add `components/Dialog.tsx` (native `<dialog>` with `showModal()`, a close button, and closing on Escape and on a backdrop click) and the player detail dialog: names used, short key, first and last seen, sessions, all totals, damage, average ping, a per-weapon table, achievements, extra gametype stats, and the "no match statistics recorded yet" state. Rows open it on click and on Enter or Space. Verify tests: opening from a row by mouse and by keyboard, the per-weapon rows, Escape and the close button returning focus to the row, the no-match-stats message, and a 404 shown as an error.
- [x] 7.4 Style the table wrapper (`overflow-x: auto`), headers, the bot marker and the dialog (`width: min(40rem, 100vw - 2rem)`, internal scroll) in `styles.css`. Verify a test at a 375px viewport that the document does not overflow horizontally with the table and with the dialog open.

## 8. Documentation

- [x] 8.1 Update the README:
  - a "Players" section: what is recorded, identity by key then name, time playing versus time on server, bots hidden by default, no IP addresses, history kept forever
  - the XonStat trade-off and the reserved `g_playerstats_gamereport_uri`, in "Server settings"
  - `players.db` in "Where things live"

  Verify `tests/test_readme.py` passes and every path and cvar named matches the code.
- [x] 8.2 Add a CHANGELOG entry for the release that ships this. It must name the stop of XonStat submission and the new Players section. Verify `.github/scripts/release-notes.sh` extracts the section for the bumped version.

## 9. Integration check

- [x] 9.1 Run the full suites (`pytest`, `ruff check`, `ruff format --check`, `npm --prefix web run lint`, `npm --prefix web test`, `npm --prefix web run build`). Verify all pass.
- [x] 9.2 On the test LXC, upgrade to a build of this change and play a short match with a real client and bots. Verify:
  - the Players section lists the human with frags, time playing and time on server, and the detail dialog shows weapons
  - the Console tab shows no report lines
  - the database survives a panel restart
  - typing `g_playerstats_gamereport_uri` in the Console tab reports its value as `-`

## Workflow follow-up

- Bump the version with the CHANGELOG entry from 8.2 when releasing.
- Archive the change once 9.2 has passed on the LXC.
