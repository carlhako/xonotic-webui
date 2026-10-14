# Changelog

Each released version has a section headed `## <version> - <date>`. The release workflow
publishes that section as the GitHub release notes, which the panel shows on its Panel
page before you upgrade. A tag without a section here is not published, so add the entry
with the version bump.

## 0.2.1 - 2026-10-14

### What's new

- **Patch release to exercise one-click upgrade end to end.** There are no behaviour
  changes. It is the first release that a 0.2.0 install can upgrade to from the Panel page.

## 0.2.0 - 2026-10-14

### What's new

- **The panel shows its version, and tells you when there is a newer one.** The header
  shows the running version in brackets beside the name: green, `[0.2.0]`, when it is
  current, and orange, `[0.2.0 update available]`, when a newer release exists. It checks
  GitHub shortly after start and every 12 hours, keeps the result across restarts, and says
  nothing when it cannot reach GitHub. Set `XONOTIC_WEBUI_RELEASE_CHECK_ENABLED=false` on a
  host with no internet.
- **A Panel page** (open it from the version in the header) with the installed and latest
  versions, a **Check now** action, and the latest release's notes.
- **One-click upgrades.** When an update is available the Panel page offers *Upgrade to
  x.y.z*. A small root helper downloads that exact release, verifies its published SHA-256
  digests and runs its installer, which restarts the panel (and the game server with it:
  players are disconnected, and the game comes back by itself if it was running). The page
  follows the upgrade, reloads onto the new version and reports the outcome, with the
  installer's output if it failed. If the new panel does not start, the previous one is
  restored.
- **Release notes come from this changelog**, and a release without an entry is not
  published.

### Upgrading from 0.1.x

0.1.0 and 0.1.1 have no helper, so upgrade them once by hand, as root; this installs the
helper and enables the new header and Panel page:

```bash
curl -fsSL https://github.com/carlhako/xonotic-webui/releases/latest/download/install.sh | bash
```

Upgrades after that can be done from the Panel page.

## 0.1.1 - 2026-10-13

### What's new

- **Server settings in the panel.** A Settings section edits the server name, bots, limits,
  mutators and voting, each saying when it takes effect (now, next map or next start), and a
  Raw cvars tab overrides anything else from the game's full cvar list. Your `server.cfg` is
  never edited; the panel's own settings run after it.
- **Maps and match actions.** A Maps section lists the installed maps with their preview and
  supported gametypes, and sets the gametype and the map rotation. The dashboard can go to
  a map, skip the current one or restart the match, and asks first when players are
  connected.
- **The installer proves the layout.** The application and game trees are root-owned and
  the service user is checked, for real, to be unable to write to them. Re-running the
  installer repairs the ownership.

## 0.1.0 - 2026-10-13

### What's new

- First release: a web control panel for a Xonotic 0.8.6 dedicated server. Start, stop and
  restart it, watch its live console in colour, send it commands, and see the map, the
  gametype and who is connected, humans and bots separately.
- **Supervised.** Crashes are restarted with a bound, the server is stopped cleanly when the
  panel stops, and whether it should be running survives panel restarts.
- **One-command install** on Debian 12 or 13 (a Proxmox LXC works): an unprivileged service
  user, the pinned and digest-checked game, and a hardened systemd unit.
