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
- network access to `dl.xonotic.org` and GitHub (or the offline options below)

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

Options, passed as environment variables to the installer:

| variable | effect |
| --- | --- |
| `RELEASE_TAG=v0.1.0` | install that release instead of the latest |
| `XONOTIC_WEBUI_TARBALL=/path/xonotic-webui.tar.gz` | install the panel from a local release tarball |
| `XONOTIC_ARCHIVE=/path/xonotic-0.8.6.zip` | use a local game archive instead of downloading (still digest-checked) |
| `XONOTIC_WEBUI_WHEELHOUSE=/path` | resolve Python dependencies from a local directory of wheels |

## Ports

| port | purpose | open it to |
| --- | --- | --- |
| **TCP 80** | web interface (`XONOTIC_WEBUI_PORT`) | your LAN only, see Security |
| **UDP 26000** | the game (`XONOTIC_WEBUI_GAME_PORT`) | players |

## Upgrading

Re-run the install command. It replaces the application, fetches the game only if it is
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
| `/var/lib/xonotic-webui/userdir/data/server.cfg` | **your server configuration**, seeded once and never overwritten |
| `/etc/xonotic-webui/xonotic-webui.env` | optional settings overrides |
| `/etc/systemd/system/xonotic-webui.service` | the service |

Edit `server.cfg` to name your server, set a message of the day, pick a map list and so
on, then restart the server from the dashboard. The panel runs your `server.cfg` and then
forces the few settings it depends on (the event log, plain colour codes).

## Settings

Environment variables (put them in `/etc/xonotic-webui/xonotic-webui.env` as `KEY=value`),
or a TOML file at `/etc/xonotic-webui/xonotic-webui.toml`. Environment wins over the file.

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
