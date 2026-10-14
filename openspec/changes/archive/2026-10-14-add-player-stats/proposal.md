# Proposal

## Why

The panel forgets everyone the moment they leave. The roster lives in memory and is wiped
when the server stops, so an operator running a public server cannot see who plays there,
how often, for how long or how well. The server already reports all of this: through the
event log the panel parses today, through a per-slot key fingerprint, and through an
end-of-match statistics report. The panel just doesn't keep any of it.

## What Changes

- **Stable player identity.** On each human join the panel asks the server for that
  slot's key fingerprint (`sv_cmd who`, run from the server console so nothing is
  masked). Every Xonotic client generates this key on first run, and nobody can present
  another player's fingerprint. A player without one falls back to their colour-stripped
  name. Every name a player uses is recorded as an alias.
- **Live recording from the event log.** Sessions (join to part, stitched across map
  changes) give *time on server*, first seen and last seen. `:kill` lines give frags,
  deaths and suicides as they happen.
- **End-of-match report.** The panel forces `g_playerstats_gamereport_uri -`, so the game
  prints its statistics report to the console at the end of every match, including one
  cut short by a map change or shutdown. From it the panel records score, wins, matches
  finished, *time playing* (alivetime), damage dealt and taken, per-weapon accuracy and
  frags, achievements and average ping. Report lines are kept out of the Console tab.
  - **Trade-off, accepted by the operator:** the server no longer submits matches to
    XonStat (stats.xonotic.org). Matches played here stop counting toward players'
    public profiles and Elo, and the server browser shows the server as using custom
    stats.
- **Persistent history.** All of this goes into a SQLite database at
  `STATE_DIR/players.db` (stdlib `sqlite3`, no new dependency). It is stored per match,
  and totals are added up when read, so later comparisons and time windows need no
  migration. History is kept indefinitely.
- **Players section.** A new navigation entry shows a table of players with frags,
  deaths, K/D, score, wins, matches, time playing, time on server, accuracy and last
  seen. Every column sorts on click and reverses on a second click. The table has a name
  search and refreshes while open. Bots are recorded but hidden behind a "show bots"
  toggle.
- **Player detail dialog.** Clicking a row opens a dialog with everything held for that
  player: first and last seen, names used, sessions, suicides, damage, a per-weapon
  table, achievements, average ping, and a short prefix of the key fingerprint.
- **Reserved cvar.** `g_playerstats_gamereport_uri` joins the cvars the panel forces and
  refuses to let settings override.

Out of scope:

- comparing players side by side (a later refinement of the dialog)
- time-windowed views, such as the last 7 days
- resetting, deleting or merging players
- storing IP addresses
- relaying reports to XonStat
- player-facing (public) stats pages
- authentication

## Capabilities

### New Capabilities

- `player-stats`: persistent player history and the Players section. Covers how a player
  is identified (key fingerprint, then name), which names they have used, sessions and
  time on server, live frag, death and suicide counts, capturing the end-of-match report
  and what it adds, behaviour across map changes and crashes, how bots are handled, what
  is never stored, the players API, and the sortable table and detail dialog in the web
  interface.

### Modified Capabilities

- `server-settings`: the panel's reserved cvars now include the statistics report target
  (`g_playerstats_gamereport_uri`), so no setting or raw override can redirect or disable
  it.
- `server-console`: the end-of-match statistics report joins the panel's own query replies
  as output withheld from the console stream and its replayed history.

## Impact

- **Backend**:
  - new `xonotic_webui/players/` package (event and report parsing, the identity lookup,
    the recorder, and the SQLite store with its schema version)
  - the event parser learns `:kill`
  - `FORCED_CVARS` gains the report URI
  - the console gains a standing filter for unsolicited report blocks
  - the supervisor's single line sink fans out to both the status tracker and the recorder
  - new `GET /api/players` and `GET /api/players/{id}`
  - a settings entry for the database path
- **Frontend**: a Players section registered in `sections.tsx`, a sortable table, a detail
  dialog, and regenerated API types and OpenAPI snapshot.
- **Data**: a new `players.db` under the state directory, owned by the service user. It
  holds key fingerprints and names but no IP addresses. The installer needs no change,
  because the state directory already exists with the right ownership.
- **Tests**: new real-server fixtures in `tests/fixtures/xonotic/` (the `who` reply,
  `:kill` variants, a report with a human playing, re-joins on map change), and the fake
  server is extended to emit them.
- **Operators**: XonStat submission stops on first start after upgrade (see above).
