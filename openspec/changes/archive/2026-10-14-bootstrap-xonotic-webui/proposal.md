# Proposal

## Why

Running a Xonotic dedicated server means a shell, hand-edited `server.cfg`, and
`screen`/`tmux` for the console. cobble (the parent project, for Minecraft Bedrock)
already solves this shape of problem with a supervised web control panel that runs in a
Debian LXC. Xonotic has no equivalent. This change lays the foundation: a running,
installable panel that can start, stop and watch a Xonotic server from a browser.
Configuration, maps and player history build on it in follow-up changes.

## What Changes

- New project, working name `xonotic-webui` (final name and env prefix still to be chosen).
  A one-time fork-and-prune of cobble's supervisor, console, status and web-shell
  layers; not a shared library.
- A single `install.sh`, run as root on Debian 12/13 (including a Proxmox LXC), that
  creates a dedicated system user, downloads the pinned Xonotic 0.8.6 release, installs
  the app and a hardened systemd unit, and exposes UDP 26000. Re-running it is the
  upgrade path.
- A new **public GitHub repository** for the project, so releases and `install.sh`
  download anonymously. The app is distributed as a GitHub release (wheel with the
  prebuilt frontend bundle plus `install.sh`), installed with `curl ... | bash`, as
  cobble does.
- A supervisor that spawns `xonotic-linux64-dedicated` with `-userdir`, drives it over
  stdin/stdout (no rcon), restarts it after crashes with a bounded backoff, and stops it
  gracefully.
- A live console: streamed server output and a command line.
- Server status (stopped / starting / running / stopping, current map and gametype,
  player count) pushed to the browser by SSE.
- A web UI shell: header, connection banner, section navigation, timezone display.
- A spike, recorded in the design: capture real eventlog, `status 1` and `cvarlist`
  output from a live 0.8.6 server so later changes parse real data.

Explicitly **out of scope** (cobble features deliberately not carried over): backups,
scheduled maintenance, self-update and the root upgrade helper, Xonotic version
updates, world-import, and allowlists. Out of this change but planned next:
`config-and-maps` (curated settings tabs, generic cvar editor, map and rotation
controls) and `player-history` (sessions, matches, per-match stats).

## Capabilities

### New Capabilities

- `installation`: root-run install script that provisions the user, pinned Xonotic
  release, app, systemd unit and firewall-relevant port, and is safely re-runnable.
- `server-lifecycle`: starting, stopping and restarting the Xonotic dedicated server
  under supervision, including crash-restart and graceful shutdown.
- `server-console`: live server output and command input from the browser.
- `server-status`: current server state and basic live facts (map, gametype, player
  count), streamed to clients.
- `web-ui-shell`: the browser application frame that hosts the sections: navigation,
  connection state, and display conventions.

### Modified Capabilities

<!-- None: this is a new project with no existing specs. -->

## Impact

- New codebase: Python (FastAPI, uvicorn, pydantic) backend; React/Vite frontend shipped
  prebuilt inside the wheel, so the server needs no Node or compiler.
- Runtime on the LXC: one systemd service, one unprivileged system user, the Xonotic
  tree (about 1.2 GB download), app state under `/var/lib/<name>`.
- Network: UDP 26000 (game) and the web port (default 80 via `CAP_NET_BIND_SERVICE`).
  LAN-only, no authentication, same stance as cobble.
- External dependencies: `dl.xonotic.org` for the pinned 0.8.6 zip (sha256 pinned in the
  script once computed); GitHub for app releases.
- Reference only (read, not modified): <https://github.com/carlhako/cobble> (cobble).
