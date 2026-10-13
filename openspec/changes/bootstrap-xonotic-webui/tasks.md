# Tasks

## 1. Repository

- [ ] 1.1 Confirm the final project name with the user (default `xonotic-webui`) and record it in the single constants spots named in design D16; verify the chosen name appears nowhere else hard-coded after the scaffold task
- [x] 1.2 `git init` this directory with branch `main`; add `.gitignore` (venv, `__pycache__`, `node_modules`, `dist`, `src/*/static`, caches) and decide whether `.claude/` and `.pi/` are committed or ignored; verify `git status` is clean of generated files
- [x] 1.3 Add an MIT `LICENSE` and a stub `README.md` (what it is, requirements, one-line install placeholder); verify both files are committed
- [x] 1.4 Confirm the repo name and public visibility with the user, then create the **public** GitHub repository under `carlhako` and push `main` (`gh repo create carlhako/<name> --public --source . --push --description "<one line>"`); verify `gh repo view carlhako/<name> --json visibility,url` reports `PUBLIC` and the openspec directory is visible on GitHub
- [x] 1.5 Before pushing, scan the tree for secrets and host-specific data (tokens, addresses, home paths); verify the scan finds nothing, since the repo is public (design D12)

## 2. Spike: capture real server behaviour

- [x] 2.1 Download `xonotic-0.8.6.zip` from dl.xonotic.org into a scratch location, compute its SHA-256, and record the digest and the zip's top-level directory name; verify the digest is written into the design's D13 and the installer constant list
- [x] 2.2 Run the dedicated binary with `-userdir` on a throwaway directory and a minimal `server.cfg` with the event log routed to the console; verify it starts, accepts commands on a piped stdin, and exits on `quit`
- [x] 2.3 Capture and save as test fixtures (`tests/fixtures/xonotic/`): the startup output through readiness, the `status` reply, join, part, name-change and match-start/end event lines, with and without bots and colour-coded names; verify each fixture is a real capture, not hand-written
- [x] 2.4 Determine the startup-complete line (D8), whether `sv_eventlog` set on the command line survives a `server.cfg` that sets it off (D3), and confirm stdin works as a pipe without a pty (design Risks); verify the findings are written back into design.md as resolved facts
- [x] 2.5 Record which game files the dedicated server needs and the on-disk size; verify the free-space threshold for the installer preflight is derived from the measurement

## 3. Project scaffold, settings and health

- [x] 3.1 Create `pyproject.toml` (hatchling, FastAPI, uvicorn, pydantic, pydantic-settings, ruff/pytest dev extras, wheel force-includes the static bundle), `src/<pkg>/` layout and `tests/`; verify `pip install -e .[dev]` succeeds and `pytest` collects
- [x] 3.2 Implement settings with the precedence env over TOML over defaults and the keys in design D6; verify unit tests cover each precedence level and invalid values
- [x] 3.3 Implement logging, the app factory, the uvicorn entrypoint with a bounded graceful-shutdown window, and `GET /health` returning the panel version regardless of server state; verify a test for server-stopped health (server-status: liveness check)
- [x] 3.4 Serve the built static bundle with SPA fallback that does not shadow `/api` or `/health`; verify tests for root, deep-link reload and a non-existent API path (web-ui-shell: served by the panel)

## 4. Supervisor (server-lifecycle)

- [x] 4.1 Add the fake dedicated server test double driven by the spike fixtures (startup output, ready line, event lines, `status` reply, honours `quit`, optional crash and hang modes); verify it runs standalone from the test suite
- [x] 4.2 Port the process wrapper (spawn with `-userdir` and game port, line reader, stdin writer, signals) and the four-state machine with compare-and-transition; verify unit tests for each legal and illegal transition
- [x] 4.3 Implement start with readiness detection and timeout, and the missing-installation error; verify tests: ready within timeout, never ready, exit during startup, game files missing
- [x] 4.4 Implement graceful stop (`quit`, wait, `SIGTERM`, `SIGKILL`) and restart as a single operation; verify tests for clean exit and for a server that ignores `quit`
- [x] 4.5 Implement conflict rejection (start while running, stop while stopped, request during transition); verify one test per scenario in server-lifecycle
- [x] 4.6 Implement bounded crash restart (threshold, window, zero disables) and crash recording; verify tests for single crash, crash loop and disabled
- [x] 4.7 Persist intended run state to `state.json` and restore it on panel start; verify tests for restart-while-running, deliberately stopped, and crash not altering intent
- [ ] 4.8 Stop the server cleanly on panel shutdown with no orphan process; verify with a test that the child is gone after the app exits and with `KillMode`/timeouts reasoned in the unit file comments

## 5. Console (server-console)

- [x] 5.1 Port the bounded console buffer and fan-out with replay-on-connect and no duplicated lines; verify tests for ordering, two clients, buffer overflow and the connect-time replay
- [x] 5.2 Insert a run-boundary marker across restarts while keeping earlier output; verify with a restart test
- [x] 5.3 Implement command submission: delivered while running, rejected while stopped, rejected when empty or multi-line; verify one test per scenario
- [x] 5.4 Expose the colour-stripped form of each line for matching and implement the matching-safe stripping (`^0-^9`, `^xRGB`, `^^`); verify unit tests with real captured names from the spike
- [x] 5.5 Add the `query(matcher, timeout)` helper used by the status tracker; verify tests for reply, timeout and server-stopped

## 6. Status (server-status)

- [x] 6.1 Implement the event-line pattern module and the status model (players with bot flag, map, gametype, last crash, restart abandoned); verify fixture-driven unit tests for join, part, rename, match start, bots vs humans
- [x] 6.2 Reconcile the player list with a `status` query when the server becomes ready and when a parse gap is detected; verify a test where events were missed
- [x] 6.3 Re-assert the event-log setting over stdin on readiness and report "event log unavailable" instead of an empty roster when it cannot be confirmed (design D3, Risks); verify a test with a config that disables it
- [x] 6.4 Clear players, map and gametype when the server stops or crashes; verify a crash-with-players test (server-status: not stale)
- [x] 6.5 Provide the snapshot and the live stream that sends the snapshot on connect and on every change; verify tests for connect, player join, state change and multi-client delivery

## 7. HTTP API

- [x] 7.1 Expose `POST /api/lifecycle/{start,stop,restart}` mapping supervisor errors to precise HTTP statuses and messages; verify API tests for success and each rejection
- [x] 7.2 Expose `GET /api/console/stream`, `POST /api/console/command`, `GET /api/status` and `GET /api/status/stream` as SSE and JSON; verify API tests with the fake server end to end (start, see output, send command, stop)
- [x] 7.3 Generate and commit the OpenAPI schema snapshot used by the front end types; verify a test fails when routes change without regenerating it

## 8. Web interface (web-ui-shell, console and dashboard views)

- [ ] 8.1 Scaffold the Vite/React/TS app with ESLint, Prettier and Vitest; verify `npm run build` emits into the Python package's `static/` and `npm test` runs
- [ ] 8.2 Implement the shell: persistent header, the section registry (Dashboard, Console), active-section highlight and in-app navigation; verify tests that sections list and switch without reload (web-ui-shell: sections navigable)
- [ ] 8.3 Implement the SSE transport with reconnect and the connection banner that refreshes state on reconnect and disables mutating controls while disconnected; verify tests with a fake EventSource for loss and recovery
- [ ] 8.4 Implement the dashboard: state, map, gametype, players (humans and bots), lifecycle controls enabled per state, error display; verify one test per scenario in the dashboard requirement
- [ ] 8.5 Implement the stop/restart confirmation when humans are connected, stating the count; verify tests with and without players
- [ ] 8.6 Implement the Console section: scrolling output, auto-scroll with pause, command input, disabled when stopped, run-boundary marker display; verify component tests
- [ ] 8.7 Implement the colour-code renderer (`^N`, `^xRGB`, `^^`, malformed input) and use it for console lines and player names; verify unit tests including the edge cases listed in design Risks
- [ ] 8.8 Display all timestamps in the browser's local timezone and make the layout usable at 375px without horizontal scroll; verify a formatting test and a screenshot check at phone width

## 9. Installer, service and release

- [ ] 9.1 Write `deploy/xonotic-webui.service` (unprivileged user, `CAP_NET_BIND_SERVICE` only, hardening, `TimeoutStopSec` above the shutdown timeout, `Restart=on-failure`); verify with `systemd-analyze verify`
- [ ] 9.2 Write `deploy/install.sh` preflight: root, amd64, apt, free-space check from task 2.5; verify by running it as non-root and with a mocked architecture and low-space condition (installation: platform requirement)
- [ ] 9.3 Implement user creation, directory layout, root-owned application and game tree and writable userdir; verify ownership and the service user's inability to write the app tree
- [ ] 9.4 Implement the game archive download with resume, pinned SHA-256 check, local-archive path, and cleanup on mismatch; verify a corrupted-archive test leaves no unverified files
- [ ] 9.5 Implement panel install from the release tarball with prebuilt wheels only, `RELEASE_TAG` pinning and offline tarball path; verify a run with no Node or compiler present
- [ ] 9.6 Seed `server.cfg` only when absent with the event log enabled and never overwrite; verify a re-run leaves an edited file byte-identical
- [ ] 9.7 Implement the venv swap, health wait and rollback on failure plus the final URL and game-port report; verify a simulated bad release restores the previous version and exits non-zero
- [ ] 9.8 Add `.github/workflows/ci.yml` (ruff, pytest, frontend lint and tests) and `.github/workflows/release.yml` (tag build, bundle-in-wheel assertion, publish tarball and `install.sh`); verify CI is green on `main` and a test tag produces both release assets
- [ ] 9.9 Write the README: requirements, the install one-liner for the public repo, ports to open (web, UDP 26000), filesystem layout, settings table, re-run-to-upgrade, security stance (LAN only, no auth); verify every documented command was executed once as written

## 10. End-to-end verification

- [ ] 10.1 On a clean Debian 13 LXC, install with the one-liner from the public repo and open the web UI; verify the installer exits zero and prints a working URL
- [ ] 10.2 With a real game client, join the server, change name, leave; verify the dashboard shows the player and the console shows the lines with colours rendered
- [ ] 10.3 Exercise start, stop, restart, kill -9 of the game process (crash restart) and a crash loop; verify behaviour matches server-lifecycle scenarios
- [ ] 10.4 Re-run the installer on the live container; verify server configuration is unchanged, no re-download occurs, and the server comes back
- [ ] 10.5 Walk every scenario in the five specs and tick them off; verify none is unexercised, and run `openspec validate bootstrap-xonotic-webui --strict`

## Workflow follow-up

- Archive the change once 10.x passes.
- Open the follow-up changes `config-and-maps` and `player-history` using the spike fixtures.
