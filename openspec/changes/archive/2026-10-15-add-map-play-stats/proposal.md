# Proposal

## Why

The panel already records every match, with its map and every player's frags, but the Maps
section cannot say how much a map is actually played. An operator choosing what to keep,
what to put in the rotation or which uploaded package to delete has no way to tell a map
that is played every night from one that has never run. This change surfaces what is
already recorded: how often each map has been played and how many frags it has seen.

## What Changes

- **Per-map totals on the map list.** Every map in `GET /api/maps` gains `played` (finished
  matches), `frags` (all frags recorded on it, bots included) and `last_played`. They are
  `null` when player history is not being recorded, so the map list never fails because of
  it.
- **Shown in both Maps views.** The card view shows `Played 42× · 1,380 frags` under the
  package line. The table view gains right-aligned **Played** and **Frags** columns. A map
  with no history shows 0, and a map with no figures available shows "–".
- **Sorting.** A single "Sort by" control, shared by both views and remembered in the
  browser: Name (default), Most played, Most frags, Recently played. Ties fall back to
  name.
- **Played filter.** A "Played / Never played" filter that combines with the existing
  gametype and favourites-only filters. Its main use is finding maps that were installed
  and never run.
- **Map details dialog.** Activating a map's title in either view opens a dialog with:
  matches played and cut short, total frags, first and last played, a per-gametype
  breakdown, and the top fraggers on that map. A top fragger opens the existing player
  dialog. Bots appear in the list with a bot badge.
- **New endpoint** `GET /api/maps/{name}/stats` behind the dialog.
- **Player database schema v2:** an index on `matches(map)`, applied by the existing
  forward-only migration.

Out of scope: total time played per map; paging or searching within the top fraggers;
per-map charts or history over time; any change to what is recorded; sorting by clicking
table column headings (the shared Sort by control covers both views); deleting recorded
history for a map.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `player-stats`: adds per-map totals (what counts as played, frags and last played), the
  map details they feed, and their availability from the API and when history is off.
- `map-control`: the installed-map list carries the per-map totals; both Maps views show
  them; the Maps section gains sorting by them, the played filter, and the map details
  dialog.

## Impact

- **Backend**: `src/xonotic_webui/players/store.py` gets two read queries (all-map totals;
  one map's detail) and the schema v2 migration; `src/xonotic_webui/api/maps.py` makes
  `GET /api/maps` fill the new fields and adds `GET /api/maps/{name}/stats`;
  `src/xonotic_webui/api/schemas.py` gets the new models. `web/openapi.json` and
  `web/src/api/schema.d.ts` are regenerated.
- **Frontend**: `web/src/sections/Maps.tsx` (sort and filter state, card line, dialog
  trigger), `web/src/components/MapTable.tsx` (two columns, dialog trigger), a new
  `MapDialog` component reusing `Dialog` and `PlayerDialog`, `web/src/styles.css`.
- **Dependencies**: none.
- **State**: the existing player database is migrated in place on first start; no new
  files. Downgrading to a panel that predates schema v2 is refused by the existing
  newer-schema guard.
- **Docs**: README Maps section notes the new columns, sorting and the details dialog.
