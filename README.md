# xonotic-webui

A web control panel for a **Xonotic dedicated server**.

Start, stop and restart your server from a browser, watch its live console and send it
commands, and see the current map, gametype and who is connected, humans and bots
separately, with their names in colour. It is a single small Python service with a
prebuilt web interface: no Node and no compiler on the server.

Designed for running at home on your LAN in a **Proxmox LXC**, but it runs just as well on
any **Debian 12 or 13** VM or bare-metal install.

- **Dashboard**: server state, map, gametype, players, and start / stop / restart controls
  that ask before disconnecting anyone.
- **Console**: live server output (colours rendered) and a command line.
- **Supervised**: crashes are restarted with a bound; the server is stopped cleanly when
  the panel stops; whether it should be running survives panel restarts.

Xonotic **0.8.6** is the only supported game version.

## Requirements

- Debian 12 or 13, **amd64** (a Proxmox LXC works)
- root, to install; the panel and the game server then run as an unprivileged user
- about **1.2 GB to download** and about **3 GiB of free disk** while installing
- network access to `dl.xonotic.org` (the game), `github.com` (the panel release), the
  Python package index (the panel's dependencies, as prebuilt wheels) and your Debian
  mirror; the offline options below replace the first three

## Install

On a fresh minimal LXC, `curl` is missing, so install it first, then run the installer as
root:

```bash
apt-get install -y curl
```

```bash
curl -fsSL https://github.com/carlhako/xonotic-webui/releases/latest/download/install.sh | bash
```

When it finishes it prints the web address and the game port. The installer is safe to
read first; it is `deploy/install.sh` in this repository.

The installer is the same whether you are installing or upgrading. It refuses to start,
before changing anything, unless it is run as root on a 64-bit x86 Debian-family system
with `apt-get` and, if the game is not yet installed, enough free disk. It then installs `python3`, `python3-venv`, `curl`,
`unzip`, `ca-certificates`, `libstdc++6` and `zlib1g`, creates the unprivileged
`xonotic-webui` user, downloads the game and checks it against a pinned SHA-256, installs
the panel into its own virtualenv, and enables and starts the `xonotic-webui` systemd
service.

Options are environment variables that must reach `bash`, so put them after the pipe:

```bash
curl -fsSL https://github.com/carlhako/xonotic-webui/releases/latest/download/install.sh | RELEASE_TAG=v0.1.0 bash
```

| variable | effect |
| --- | --- |
| `RELEASE_TAG=v0.1.0` | install that release instead of the latest |
| `XONOTIC_WEBUI_TARBALL=/path/xonotic-webui.tar.gz` | install the panel from a local release tarball |
| `XONOTIC_ARCHIVE=/path/xonotic-0.8.6.zip` | use a local game archive instead of downloading (still digest-checked) |
| `XONOTIC_WEBUI_WHEELHOUSE=/path` | resolve Python dependencies from a local directory of wheels |
| `XONOTIC_WEBUI_REPO=owner/name` | take the release from another GitHub repository, such as a fork |

The release assets are `install.sh` and `xonotic-webui.tar.gz`. To install without
downloading anything from GitHub or `dl.xonotic.org`, save both from the release page,
fetch the game archive and a wheelhouse yourself, and run the saved script as root:

```bash
XONOTIC_WEBUI_TARBALL=/path/xonotic-webui.tar.gz XONOTIC_ARCHIVE=/path/xonotic-0.8.6.zip XONOTIC_WEBUI_WHEELHOUSE=/path/wheels bash install.sh
```

The installer still uses `apt-get` for the runtime packages in either case.

## Ports

| port | purpose | open it to |
| --- | --- | --- |
| **TCP 80** | web interface (`XONOTIC_WEBUI_PORT`) | your LAN only, see Security |
| **UDP 26000** | the game (`XONOTIC_WEBUI_GAME_PORT`) | players |

Both are the defaults; if you change a port in the settings below, open that one instead.
The installer opens nothing itself, so allow these in any firewall on the host or in front
of it.

## Upgrading

Re-run the install command from Install, as root. It replaces the application, fetches the game only if it is
missing, and leaves your server configuration, panel state and logs untouched. The new
version is built beside the old one and checked before the old one is removed; if the new
panel does not answer its health check, the previous version is restored and the installer
exits non-zero. Pin a version with `RELEASE_TAG`.

## Where things live

| path | what |
| --- | --- |
| `/opt/xonotic-webui/venv` | the application, root-owned |
| `/opt/xonotic/0.8.6` | the game tree, root-owned and read-only to the service |
| `/var/lib/xonotic-webui/state.json` | whether the server should be running |
| `/var/lib/xonotic-webui/settings.json` | the server settings saved from the panel (see Server settings) |
| `/var/lib/xonotic-webui/userdir/data/server.cfg` | **your server configuration**, seeded once and never overwritten |
| `/var/lib/xonotic-webui/userdir/data/xonotic-webui-settings.cfg` | generated from `settings.json` on every save and start; do not edit |
| `/etc/xonotic-webui/xonotic-webui.env` | optional settings overrides, seeded with commented examples and never overwritten |
| `/etc/xonotic-webui/xonotic-webui.toml` | optional settings file, not created by the installer |
| `/var/cache/xonotic-webui` | the resumable game download, removed once it is verified and extracted |
| `/etc/systemd/system/xonotic-webui.service` | the service |

The service is `xonotic-webui` and runs as the unprivileged user of the same name. Everything
under `/var/lib/xonotic-webui` belongs to that user; `/opt` and `/etc` are root's, so the
service cannot modify the application or the game. The panel's own log goes to the journal:
`journalctl -u xonotic-webui`.

You can configure the server in two places, which work together (next section): your
`server.cfg`, and the panel's **Settings** and **Maps** sections.

## Server settings

The panel keeps its own settings in `settings.json` and generates
`xonotic-webui-settings.cfg` from them. The server is started with a wrapper config that
runs, in this order:

1. your `server.cfg`, which the panel **never edits**
2. the generated `xonotic-webui-settings.cfg`
3. the few cvars the panel depends on (the event log, plain colour codes)

So **a value saved in the panel wins over the same setting in `server.cfg`**, and nothing
can switch the event log off. A setting that `server.cfg` also sets is marked in the panel,
as far as simple `name value`, `set` and `seta` lines reveal. With nothing saved in the
panel, the server behaves exactly as `server.cfg` configures it. Settings can be changed
while the server is stopped; they are then applied at its next start.

Each saved setting says when it takes effect:

| when | meaning | examples |
| --- | --- | --- |
| **now** | sent to the running server immediately | server name, bots, bot skill, a time limit |
| **next map** | accepted at once, applied when the next map loads | mutators, voting, gametype, going back to a limit's "map default" |
| **next start** | needs a restart | maximum players (the panel offers the restart) |

Limits are written as the game's `*_override` cvars, so they apply to every map and not
just the current match. **Raw cvars** lets you override any other cvar (search the game's
full list, with defaults and descriptions); a raw override is applied after the curated
settings, and may need a map change or restart to take effect. The panel refuses to
override the cvars it forces, the game port and `rcon_password`.

The panel lists maps from the `.pk3` packages in the game and in `userdir/data`, and keeps
the gametype and the map rotation in `settings.json` too. An empty rotation means every map
that supports the gametype.

Values may not contain a line break, a double quote or a backslash; everything else,
including `;`, `$` and colour codes such as `^1`, reaches the server exactly as typed.

## Maps and match actions

The **Maps** section lists the installed maps (title, supported gametypes, preview) even
while the server is stopped, and lets you choose the gametype and the rotation. Three
actions are also on the dashboard:

| action | what the game does |
| --- | --- |
| **Go to map** | ends the match with the scoreboard, then loads that map; no vote |
| **Skip** | ends the match early; then the game's normal vote (if players are connected and voting is on) or the next map in the rotation |
| **Restart match** | reloads the current map at once and resets scores |

With players connected you are asked to confirm, and told how many are in the match. Each
action is shown as pending to every open browser until the next match actually starts, and
as not completed if none starts within 90 seconds.

**Idle auto-pause stays on.** An empty dedicated server pauses itself a few seconds after a
map loads (the **Pause when empty** setting) and resumes when a player joins; that keeps an
idle server's CPU use near zero. While it is paused the game accepts *go to map* and *skip*
but does nothing until it resumes, so after sending one the panel resumes the server just
long enough to carry it out; the new map pauses itself again. The panel does this only when
nobody is connected, so players never see a pause message, and the pause commands do not
appear in the console.

A map without a `.mapinfo` file is listed with unknown gametypes and is not offered for any
gametype. Changing the gametype takes effect at the next map; to switch immediately, pick a
map for it and the panel goes to that map.

## Settings

Environment variables (put them in `/etc/xonotic-webui/xonotic-webui.env` as `KEY=value`),
or a TOML file at `/etc/xonotic-webui/xonotic-webui.toml` (or the path in
`XONOTIC_WEBUI_CONFIG_FILE`) with the same names, lower-case and without the prefix, for
example `port = 8080`; they may be at the top level or under an `[xonotic_webui]` table.
Environment wins over the file. Restart the panel after changing either:
`systemctl restart xonotic-webui`.

| variable | default | meaning |
| --- | --- | --- |
| `XONOTIC_WEBUI_PORT` | `80` | web interface port |
| `XONOTIC_WEBUI_HOST` | `0.0.0.0` | address the web interface binds |
| `XONOTIC_WEBUI_GAME_PORT` | `26000` | UDP game port |
| `XONOTIC_WEBUI_GAME_ROOT` | `/opt/xonotic/0.8.6` | the extracted game tree |
| `XONOTIC_WEBUI_STATE_DIR` | `/var/lib/xonotic-webui` | panel state and the game's userdir |
| `XONOTIC_WEBUI_SHUTDOWN_TIMEOUT` | `60` | seconds to wait for a clean exit before forcing |
| `XONOTIC_WEBUI_READINESS_TIMEOUT` | `120` | seconds to wait for the server to become ready |
| `XONOTIC_WEBUI_CRASH_RESTART_THRESHOLD` | `3` | crashes in the window after which automatic restart is abandoned; `0` disables it |
| `XONOTIC_WEBUI_CRASH_RESTART_WINDOW` | `300` | the window, in seconds |
| `XONOTIC_WEBUI_CRASH_RESTART_DELAY` | `2` | seconds to wait before an automatic restart |
| `XONOTIC_WEBUI_CONSOLE_BUFFER_LINES` | `2000` | console lines kept for new viewers |
| `XONOTIC_WEBUI_CONFIG_FILE` | `/etc/xonotic-webui/xonotic-webui.toml` | the TOML file to read; only meaningful as an environment variable |

The service unit itself sets `XONOTIC_WEBUI_GAME_ROOT` and `XONOTIC_WEBUI_STATE_DIR` in the
environment, so under systemd the TOML file cannot change them; set them in the `.env` file.

If you raise `XONOTIC_WEBUI_SHUTDOWN_TIMEOUT`, raise `TimeoutStopSec` in the unit by the
same amount (the unit's comments explain the arithmetic).

## Security

The panel has **no authentication** and no TLS. Anyone who can reach its port can start
and stop the server and send it console commands. Run it on a trusted LAN, do not forward
its port from your router, and expose only the game's UDP port to the internet. The
binding address is configurable if you want to restrict it further.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

```bash
npm --prefix web ci
npm --prefix web test
npm --prefix web run build
```

`npm run build` writes the interface into `src/xonotic_webui/static/`, which the panel
serves and the wheel carries. To work on the interface with live reload, run the panel on
an unprivileged port and point the dev server at it:

```bash
XONOTIC_WEBUI_PORT=8000 .venv/bin/python -m xonotic_webui
```

```bash
XONOTIC_WEBUI_PORT=8000 npm --prefix web run dev
```

After changing an API route or model, regenerate the schema snapshot and the front end's
types (a test fails until you do):

```bash
.venv/bin/python scripts/export_openapi.py
npm --prefix web run gen:api
```

The tests never need the 1.2 GB game: a fake dedicated server (`tests/fake_xonotic`)
replays output captured from the real one (`tests/fixtures/xonotic`).

This project was bootstrapped with [OpenSpec](https://openspec.dev); the specifications and
design decisions are in `openspec/`.

## Licence

MIT
