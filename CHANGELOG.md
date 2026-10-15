# Changelog

Each released version has a section headed `## <version> - <date>`. The release workflow
publishes that section as the GitHub release notes, which the panel shows on its Panel
page before you upgrade. A tag without a section here is not published, so add the entry
with the version bump.

## 0.4.0 - 2026-10-15

### What's new

- **See how much each map is played.** Every map shows how many matches have been played on
  it and how many frags were scored, as `Played 42× · 1,380 frags` on a card and as two
  columns in the Files table. A map that was never played shows 0. "Played" counts matches
  that ran to their limit; matches cut short still add their frags.
- **Sort and filter by it.** A **Sort by** control (Name, Most played, Most frags, Recently
  played) and a **Played / Never played** filter work in both views, combine with the
  gametype and favourites filters, and are remembered in the browser. Never played is the
  quick way to find maps that were installed and never run.
- **Map details.** Click a map's title for its matches played and cut short, frags, first
  and last played, matches per gametype and its top ten fraggers; a fragger opens that
  player's details.
- **Upload, download and delete map packages** from the Maps section. Only `.pk3` files are
  accepted and each is checked before it is installed. Delete asks first and names every
  map in the file. A package added while the server runs is listed but needs a server
  restart before the game can use it.
- **A Files view** beside the Cards: a table with one row per map showing the package it
  comes from and its size, with the same *Go to this map* and *Add to rotation* buttons.
- **Favourites.** Star a map and narrow either view to *Favourites only*. They are kept by
  the panel, so every browser sees the same ones.
- **A Voting enabled switch** in the Settings Voting tab, so map voting is turned off with a
  switch instead of setting "Maps in the vote" to 0.

### Changes you should know about

- **The player database is migrated on first start** (an index is added; no data is
  rewritten). A panel older than 0.4.0 will refuse to open the migrated file, so keep a
  copy of `players.db` if you may want to go back.
- **The map list is sorted by name** by default; it used to follow the game's order.

## 0.3.0 - 2026-10-14

### What's new

- **A Players section.** The panel now keeps a history of everyone who plays on the server
  and shows it as a table you can sort by any column (frags, deaths, K/D, score, wins,
  matches, time playing, time on server, accuracy, last seen), search by name, and page
  through. Click a player for their names, sessions, per-weapon accuracy and achievements.
  Bots are recorded but hidden unless you show them. The history lives in
  `/var/lib/xonotic-webui/players.db` and is kept across restarts and upgrades. No IP
  addresses are stored.
- **Players are identified by their key, not their name.** A rename or a new address keeps
  one history; a player with no key falls back to their name.

### Changes you should know about

- **The server no longer submits matches to XonStat (stats.xonotic.org).** To read the
  end-of-match report the panel sets `g_playerstats_gamereport_uri` to `-` at every start,
  and the game can send the report to only one place. Matches played here stop counting
  toward players' public XonStat profiles and Elo, and the server browser shows the server
  as using custom stats. The cvar is now reserved, and the "Report match statistics" setting
  is removed.

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
