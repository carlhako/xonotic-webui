# Tasks

## 1. Real-server captures (needs a human joined to the test server)

- [x] 1.1 On the test LXC (10.0.1.147), with the operator joined as a player and `bot_number 2`, capture a mid-match deathmatch reply to the full batched line from design D1 (via `POST /api/console/command` and `GET /api/console/stream`). Include one client spectating. Save it as `tests/fixtures/xonotic/match_dm_live.txt`. Verify the file has the global lines, the cvar lines, the `status 1` reply, `:status:`…`:end` with a `:player:` line per client, and `stats dumped.`.
- [x] 1.2 Switch to team deathmatch (and, if time allows, CTF) and capture the same reply into `match_tdm_live.txt` (and `match_ctf_live.txt`). Verify the `:labels:teamscores:` and `:teamscores:` lines and the team numbers, and record the spectator and team encodings in the fixture README.
- [x] 1.3 Capture the clock edge cases into `match_clock_cases.txt`: the countdown just after a map load, warmup with `g_warmup 1` and a `g_warmup_limit`, overtime or an `sv_cmd extendmatchtime`, intermission after the match ends, and an autopaused server. Record which values each phase showed in the fixture README. Confirm or correct the warmup formula in design D3 and update design.md if it differs. Restore every changed setting afterwards (`g_warmup`, gametype, `bot_number 2`) and verify the panel's Settings page shows the original values.

## 2. Parser and clock

- [x] 2.1 Add `src/xonotic_webui/match/` with `MatchReplyCollector` (design D1): it consumes the global, cvar, `status 1` and dump lines and finishes on `stats dumped.`, consuming DarkPlaces' unknown-global error lines too. Verify with tests in `tests/test_match_parser.py` that feed the task-1 fixtures, plus a fixture with an unknown global, that every line is consumed and nothing else is.
- [x] 2.2 Parse the dump into columns, players, spectators and teams (design D5): label suffixes, `elo`/`rounds_pl`/unnamed columns dropped, `:player:` split from the right, ping and bot joined from `status 1`, game sort order with lower-is-better, team colours. Verify with tests on each task-1 fixture, including a name containing `:` and a line that cannot be parsed being skipped.
- [x] 2.3 Compute the clock (design D3) and the score limit (design D6) from one reply. Verify with table tests for each phase: playing with and without a limit, countdown, warmup, overtime, ended, a raised limit, and left floored at 0.

## 3. Fake server

- [x] 3.1 Teach `tests/fake_xonotic/server.py` to answer `prvm_global server <name>` (the globals in D1, with an unknown name answered like DarkPlaces), and `sv_cmd printstats` with a `:status:` dump of its roster and per-player scores, followed by `stats dumped.`. Server `time` advances while unpaused and stops while autopaused or paused. Document the new behaviour and any new `FAKE_XONOTIC` flags in its docstring, and add test-only commands to set scores, teams and warmup. Verify with new cases in `tests/test_fake_server.py`, and that its replies parse with the task-2 parser.

## 4. Watcher and API

- [x] 4.1 Add `MatchWatcher` (design D2, D4, D7): it polls once a second only while subscribed and `RUNNING`, publishes on change with latest-wins queues, infers paused, degrades each part, and keeps the last snapshot on timeout. Wire it into `runtime.py` and close it in `aclose`. Verify with tests against the fake server:
  - no queries without subscribers
  - polling starts and stops with subscribers and with the server state
  - paused is reported while autopaused
  - the scoreboard is unavailable with `no_dump` while the clock still shows (the real 0.8.6
    prints the dump even with `sv_eventlog 0`, so the fake's `eventlog_off` does not drop it)
  - `live: false` after a stop
- [x] 4.2 Verify the console stays clean: a test that runs the watcher for a few ticks while a console client is streaming asserts that none of the poll's lines are delivered or replayed, and that a `status 1` reconcile issued during a tick still gets its own reply.
- [x] 4.3 Add `GET /api/match` and `GET /api/match/stream` in `api/match.py` with models in `api/schemas.py` (design D7 shape). Verify with tests in `tests/test_api_match.py`: snapshot shape while running and stopped, the stream's first event being the current snapshot, and the snapshot endpoint not starting polling.
- [x] 4.4 Regenerate `web/openapi.json` (`.venv/bin/python scripts/export_openapi.py`) and `web/src/api/schema.d.ts` (`npm --prefix web run gen:api`). Verify `tests/test_openapi_snapshot.py` passes.
- [x] 4.5 Add a "Live match" subsection to the README's Maps and match actions area. Cover what the dashboard shows, that it polls only while the dashboard is open, the two endpoints, and the `sv_eventlog_files` note from the design's risks. Verify `tests/test_readme.py` passes.

## 5. Dashboard

- [x] 5.1 Add a `useMatch()` hook over `useEventSource` that opens `/api/match/stream` only while mounted. Verify with a test using `fakeEventSource` that the stream opens on mount, closes on unmount, and applies each event.
- [x] 5.2 Add the match clock card to the Dashboard (design D8):
  - playing: `m:ss` left and the limit
  - countdown: "Starting in m:ss"
  - other phases: "Warmup", "Overtime", "Match over"
  - paused: a badge
  - beside it: the score limit with its unit
  - clock unavailable: "Clock unavailable"

  Verify with tests in `web/src/test/match.test.tsx` for each phase, paused, and unavailable.
- [x] 5.3 Add the Scoreboard panel (design D8):
  - players in the game's order, with their game colours
  - the game's columns plus Ping and Time, fractional values rounded
  - bots marked
  - team games: a coloured team-total header above each team's players
  - spectators on a muted line underneath
  - "Players online" shown instead, with the reason, when the scoreboard is unavailable

  Add its styles to `styles.css`. Verify with tests in `web/src/test/match.test.tsx` for deathmatch, team game, spectators, unavailable, and no match (server stopped, neither clock nor scoreboard shown).
- [x] 5.4 Run `npm --prefix web test`, `npm --prefix web run lint` and `npm --prefix web run build`; verify all pass.

## 6. Integration

- [x] 6.1 Run the full Python suite (`.venv/bin/python -m pytest`) and lint; verify they pass.
- [x] 6.2 Install the build on the test LXC. With the operator joined, open the dashboard and verify, against the in-game HUD and scoreboard (Tab), that:
  - time left and scores match within a second
  - the clock freezes when the operator leaves (autopause) and resumes on rejoin
  - the Console section shows none of the polling
  - closing the dashboard stops the queries (no new internal commands in `journalctl -u xonotic-webui` debug output, or via the watcher's subscriber count)

## Workflow follow-up

- Add a CHANGELOG entry with the next version bump: a live match clock and scoreboard on the dashboard.
- Archive the change once reviewed, creating the `live-match` main spec.
