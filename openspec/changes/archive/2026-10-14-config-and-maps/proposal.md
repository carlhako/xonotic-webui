# Proposal

## Why

Configuring the server still means a shell and a hand-edited `server.cfg`, and changing
the map or gametype means typing console commands whose behaviour is far from obvious (on
an empty server they silently wait for a player to join). This change, the follow-up
planned in `bootstrap-xonotic-webui`, adds server settings and map control to the panel.
It is grounded in a spike against the live 0.8.6 server (recorded in `design.md`).

## What Changes

- **Panel-owned settings.** The panel keeps its own settings store and generates a config
  file that the wrapper config runs after the operator's `server.cfg`. `server.cfg` is
  never edited by the panel. Panel settings win over `server.cfg`.
- **Settings take effect at the right time.** Every setting is classed by when it takes
  effect (now, next map, or next start). Saving it persists it, applies it live where the
  game allows, and tells the operator when it will take effect.
- **Curated settings** for what operators change most: identity (hostname, message of the
  day, max players, public listing), match limits (time, frag/point, capture and lead
  limits, written as the game's override cvars so they survive map changes), bots, map
  voting, common mutators, idle auto-pause and stats reporting.
- **Raw cvar overrides** for any other setting, with a searchable catalogue of the game's
  cvars (name, default, description) and current live values where the server is running.
- **Map catalogue.** Installed maps, read from the game's and the user's `.pk3` packages:
  title, supported gametypes and preview image. It is available while the server is
  stopped.
- **Gametype** chosen from the gametypes the installed maps support, persisted, and applied
  at the next map.
- **Map rotation**: an ordered map list, with shuffle on or off, restricted to maps that
  support the selected gametype.
- **Match actions.** Each works on an empty, auto-paused server and is confirmed when the
  next match actually starts:
  - go to a specific map: scoreboard, then that map, with no vote
  - skip: end the match and go through the normal map vote
  - restart the current match
- Idle auto-pause stays on by default. The panel unpauses only when it must, to carry out
  an action.

Out of scope: editing or displaying `server.cfg`; uploading or downloading maps (maps
placed in the user data directory are picked up); per-gametype limit profiles beyond the
game's own per-gametype cvars; player history (the separate `player-history` change);
authentication.

## Capabilities

### New Capabilities

- `server-settings`: the panel-owned settings store and its generated configuration;
  curated settings and raw cvar overrides; validation and safe serialisation of values;
  live application and reporting of when each change takes effect; the cvar catalogue.
- `map-control`: the installed-map catalogue; gametype selection; map rotation; and the
  match actions (go to map, skip, restart match), including their behaviour on an empty,
  auto-paused server and confirmation from the next match start.

### Modified Capabilities

<!-- None. The bootstrap capabilities (server-lifecycle, server-status, web-ui-shell) keep
their requirements: new UI sections use the existing section registry, and the extra
`exec` in the wrapper config does not change any lifecycle requirement. Those specs are
not yet archived into openspec/specs, so this change adds new capabilities only. -->

## Impact

- **Backend**: a settings store under `STATE_DIR`; generation of a second panel-owned
  config file in `userdir/data/`, executed by the existing wrapper config; new HTTP
  endpoints for settings, the cvar catalogue, maps and match actions; a `.pk3` (zip)
  reader for map metadata and preview images. No new runtime dependencies (`zipfile` is
  in the standard library).
- **Frontend**: new sections (Settings, Maps) in the section registry; the dashboard gains
  match actions.
- **Console**: setting changes and actions sent by the panel appear in the console history;
  the pause probe does not. Large panel queries must not evict the operator's console history
  (see design).
- **Fixtures**: the spike's captured `cvarlist` and run transcripts are added to
  `tests/fixtures/xonotic/`, and the fake server learns the new commands.
- **Security**: values written to a config file or console line are a command-injection
  surface (`;` separates commands, `$` expands cvars). Strict validation and quoting are
  required.
