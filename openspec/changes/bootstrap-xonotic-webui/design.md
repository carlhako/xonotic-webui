# Design

## Context

See `proposal.md` for motivation and scope. The reference implementation is cobble
(<https://github.com/carlhako/cobble>): a FastAPI service that supervises one child
process over stdin/stdout, parses its output into a status model, streams to a React
SPA over SSE, and installs with a single `install.sh` into a Debian LXC.

Constraints that shape this design:

- Target is a Debian 12/13 LXC, amd64 only, installed by root, run unprivileged.
- Xonotic 0.8.6 is the only supported game version. The upstream project has not
  shipped a stable release since 2023, so version management is out of scope.
- Nothing about the Xonotic console or event log has been verified against a live
  server yet. The format details in this document come from prior knowledge and are
  treated as hypotheses until the spike (task group 2) confirms them.
- LAN-only, no authentication (same stance as cobble).

## Goals / Non-Goals

**Goals:**

- A running, installable panel that controls one Xonotic dedicated server end to end.
- Reuse cobble's proven shapes (supervisor state machine, console buffer, status
  tracker, SSE, wheel-with-bundle release) so behaviour is predictable.
- Establish the seams the next two changes need: a generic event-line parser feeding
  the status tracker, a managed data directory, and an extensible section list.

**Non-Goals:**

- Server configuration editing, map and rotation control, player history (later
  changes).
- Authentication, TLS, multi-server support, remote (non-child) servers over rcon.
- Any update, backup or scheduling mechanism.

## Decisions

### D1. One-time fork-and-prune of cobble, not a shared library

Copy the supervisor, process wrapper, state machine, console, status tracker, settings
and web shell into this repository and delete everything Bedrock-specific.

*Alternatives:* extract a shared `cobble-core` package (rejected: this is a frozen
project and a shared library would impose a release treadmill on both repos);
build from scratch (rejected: re-derives solved problems like crash-loop bounding and
SSE backpressure).

### D2. Control the server over the child's stdin/stdout, not rcon

The supervisor owns the process, writes console commands to its stdin and reads its
stdout. No `rcon_password` is configured or needed.

*Alternative:* rcon over UDP (rejected for v1: needs a secret in config, speaks a
challenge protocol, and adds nothing when the panel is the process parent). Revisit
only if managing a server the panel did not spawn becomes a goal.

### D3. Structured events come from the server's own event log on stdout

The app launches the server with the event log enabled and routed to the console
(`sv_eventlog`, `sv_eventlog_console`), and parses those lines for joins, parts, name
changes, match start and match end. Matching runs on colour-stripped text; raw lines
are retained for display.

The setting is passed on the command line **and** re-asserted over stdin when the
server reports ready, because a user `server.cfg` executed after the command line
could otherwise silently turn the event log off and blind the status tracker. The
seeded `server.cfg` also sets it.

*Alternative:* poll the `status` command on a timer (kept only as a reconcile query,
see D4; polling alone misses short sessions and match boundaries).

### D4. Status = event-driven model plus an on-demand `status` query to reconcile

The tracker applies event-log lines to an in-memory model. When the server becomes
ready, or when a gap is suspected (parser error, reconnect of the log), the tracker
issues one console query (`status`) and rebuilds the player list from its output. The
console exposes a `query(matcher, timeout)` helper (as cobble's does) for this.

### D5. Filesystem layout

```
/opt/xonotic-webui/venv/             app + deps, root-owned
/opt/xonotic/<version>/              extracted game tree, root-owned, read-only
/var/lib/xonotic-webui/              panel state (state.json: intended run state)
/var/lib/xonotic-webui/userdir/      passed as -userdir; data/server.cfg, logs, saves
/etc/xonotic-webui/xonotic-webui.env optional overrides (EnvironmentFile)
/etc/systemd/system/xonotic-webui.service
```

The game tree is immutable and separate from mutable data, mirroring cobble's
`versions/` vs `data/` split, so reinstalling never touches configuration. `userdir`
is the only place the game writes.

### D6. Settings: environment variables over TOML over defaults

Same precedence and mechanism as cobble (pydantic-settings), prefix
`XONOTIC_WEBUI_`. Initial settings: `PORT` (web, default 80), `HOST`, `GAME_PORT`
(default 26000), `GAME_ROOT`, `STATE_DIR`, `SHUTDOWN_TIMEOUT` (default 60),
`READINESS_TIMEOUT` (default 120), `CRASH_RESTART_THRESHOLD` (3),
`CRASH_RESTART_WINDOW` (300).

### D7. Lifecycle state machine and graceful stop

States `stopped | starting | running | stopping` with a compare-and-transition guard
(as cobble's `StateMachine`). Stop sends `quit` over stdin, waits
`SHUTDOWN_TIMEOUT`, then `SIGTERM`, then `SIGKILL`. systemd's `TimeoutStopSec` must
exceed that timeout plus uvicorn's drain; `KillMode=mixed` as in cobble.

Intended run state (running vs stopped) is persisted to `state.json` on every
operator-requested transition, and restored on panel start. Crash restarts do not
change intended state.

### D8. Readiness from a startup-complete line, with a fallback

Primary signal: a specific console line observed during startup (exact text decided by
the spike). Fallback: a successful `status` query reply. A timeout is a failed start.

### D9. Transport: HTTP JSON for commands, SSE for streams

`POST /api/lifecycle/{start,stop,restart}`, `GET /api/status`, `GET /api/status/stream`,
`GET /api/console/stream`, `POST /api/console/command`, `GET /health`. SSE rather than
WebSocket: one-directional, auto-reconnect, no extra dependency; identical to cobble
so the front-end transport code ports over.

### D10. Colour codes handled in the front-end; patterns on stripped text

Xonotic colour codes (`^0`..`^9`, `^xRGB`, `^^` for literal caret) are parsed by a
small front-end utility into styled spans. The backend keeps raw lines and exposes a
stripped form used for matching and for plain-text fields (e.g. player names in
status), so the same code works for later features.

### D11. Front end: React + Vite, section registry, bundle shipped in the wheel

Same stack and `sections.tsx` registry pattern as cobble, so later changes add a
section by adding one entry. Vite builds into the Python package's `static/`; the wheel
force-includes it. Node runs only in CI.

### D12. Distribution: public GitHub repo, release tarball, curl-piped installer

The project lives in a **public** GitHub repository so that release assets and
`install.sh` download anonymously with `curl | bash` and no token, which is the
install flow cobble already uses. A tag triggers a workflow that builds the frontend,
builds the wheel, asserts the bundle is inside it, and publishes `xonotic-webui.tar.gz`
and `install.sh`. The installer takes `RELEASE_TAG` to pin and a local tarball path for
offline use. Because the repo is public, nothing secret may be committed (no tokens,
no host addresses); the repo carries an MIT licence like cobble.

### D13. Game archive: pinned zip with a pinned SHA-256

The installer downloads `xonotic-0.8.6.zip` (about 1.2 GB) from dl.xonotic.org and
verifies a SHA-256 constant in the script. The digest is computed during the spike
and committed. No mirror fallback in v1 beyond a local-archive path.

*Alternative:* Debian's `xonotic-server` package (not verified; couples to the distro's
version and layout). Not chosen as the default; can be added later behind a flag.

### D14. Upgrade is re-running the installer, with venv-swap rollback

Kept from cobble: build the new venv beside the old, stop, swap, start, wait for
`/health` to report the new version, and roll back on failure. Dropped: the root
upgrade helper, `.path` unit and any in-UI upgrade.

### D15. Testability without the 1.2 GB game

A fake dedicated server (a small script that emits realistic startup, eventlog and
`status` output captured in the spike, and honours `quit`) is used by the supervisor,
console and status test suites. Real-server verification is a manual checklist on an
LXC.

### D16. Naming is a single constant

`xonotic-webui` is a working name. Paths, unit name, env prefix and package name derive
from one place in each of the installer, settings and `pyproject.toml`, so a rename
is mechanical.

## Risks / Trade-offs

- **Event-log format differs from what is assumed** → Spike first; patterns live in one
  module with fixtures captured from the real server; spec scenarios stay at behaviour
  level.
- **Server reads no commands when stdin is a pipe** (or closes on EOF) → verify in the
  spike; keep the pipe open for the child's lifetime; fall back to a pty if required.
- **User `server.cfg` disables the event log** → re-assert over stdin on readiness
  (D3) and surface "event log unavailable" in status rather than showing a wrong
  empty player list.
- **Large download fails or the disk is small in an LXC** → free-space preflight,
  resumable `curl -C -`, digest check, local-archive path.
- **Public, unauthenticated control panel** → default stance matches cobble (LAN
  only); documented in the README; binding host is configurable. Not exposing the web
  port to the internet is the operator's responsibility.
- **Fork drift from cobble** → accepted (D1); no attempt to track upstream.
- **Colour-code edge cases** (`^x` with fewer than 3 hex digits, trailing caret) →
  covered by unit tests in the front-end utility.

## Migration Plan

New project; nothing to migrate. Deployment is: tag a release, then run the installer
on the target LXC. Rollback of a bad release is automatic via D14, or by pinning
`RELEASE_TAG` to the previous tag.

## Open Questions

- Final project name (affects only D16 constants and the repo name).
- Exact top-level directory inside the Xonotic zip and whether the unused client music
  can be pruned at install to save disk (spike will show; no spec impact).
