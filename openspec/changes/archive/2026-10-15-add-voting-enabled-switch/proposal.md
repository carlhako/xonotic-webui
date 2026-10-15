# Proposal

## Why

Turning off map voting, so the server just plays the next map in the rotation, is done
today by setting "Maps in the vote" to `0`. That works, but nothing in the Voting tab says
so: it is a number field with a small "Voting off" caption, and "Vote length" stays
editable though it means nothing once voting is off. Operators looking for an on/off
control do not find one.

## What Changes

- The Voting tab gets a **Voting enabled** switch. Off greys out "Maps in the vote" and
  "Vote length"; on makes them editable.
- The switch is not a new cvar. It fronts `g_maplist_votable`: off saves `0`; on saves the
  count (1-20).
- While off, "Maps in the vote" shows the last non-zero count rather than `0`. Turning the
  switch back on restores the last non-zero count seen in this browser session, falling
  back to the setting's default (6) when none was seen, for example after a reload with
  voting already off.
- With the switch on, a count of `0` is rejected on the field with a message pointing at
  the switch, so the number field can no longer be used to turn voting off by accident.
- The behaviour is **data-driven**: a curated setting can declare a *switch* (its label,
  help text, the value that means "off" and the settings it enables). The settings API
  reports it, and the Settings UI renders any setting that has one as a switch plus its
  dependents. Voting is the first and only setting to use it.

Out of scope:

- a hint in the Maps tab that the rotation decides the next map while voting is off
- converting the time/score/lead limits ("Map default" / "No limit") to the same pattern
- storing the remembered count on the server or in browser storage across sessions
- any change to the `g_maplist_votable` cvar itself, to map-control, or to the raw API:
  `0` remains valid there

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `server-settings`: adds a requirement for the Voting enabled switch (greying, restoring
  the count, rejecting `0` while on). Curated settings otherwise unchanged.

## Impact

- `src/xonotic_webui/serversettings/registry.py`: a `Switch` description on
  `CuratedSetting`, set on `g_maplist_votable`, with an import-time consistency check.
- `src/xonotic_webui/api/schemas.py`, `src/xonotic_webui/api/settings.py`: a `switch`
  field on the setting model. This is an additive API change.
- `web/openapi.json`, `web/src/api/schema.d.ts`: regenerated.
- `web/src/sections/Settings.tsx`, `web/src/test/settings.test.tsx`,
  `web/src/test/util.tsx`: the switch rendering, remembered count and tests.
- Tests for the registry check and the API field.
