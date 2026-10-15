# Proposal

## Why

The panel is only ever used from a desktop browser, but its layout is built phone-first and
caps every page at 960px. On the Maps page the Files table does not fit in that width, so
the operator has to scroll sideways to reach a map's actions. Measured on a 0.4.0 panel, the
table needs about 1070px with only the game's own maps installed and about 1230px once
uploaded maps add their Download and Delete buttons. The table box gets only about 890px.

## What Changes

- The content area widens from 960px to 1280px on every page, not just Maps.
- The Files table on the Maps page fits at that width without sideways scrolling, uploaded
  maps included. Long map and package names wrap within their cells instead of widening the
  table.
- The interface is declared **desktop-only**. The phone-width requirements are dropped from
  the specs, along with the phone-only layout rules (the narrow-viewport media query and the
  "mobile-first" contract in the stylesheet).
- Defensive rules that also matter on a narrow desktop window stay: the table scrolls inside
  its own box rather than the page, long tokens wrap, and dialogs stay within the window.

Out of scope:

- any other layout redesign, such as multi-column dashboards or wider forms on Settings
- the live match clock and scoreboard on the dashboard, which is a separate change
- actively breaking small screens: they stop being supported, not made worse on purpose

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `web-ui-shell`: the "usable on a phone" requirement is replaced by a desktop-layout
  requirement (1280px content width, Maps Files table fits), and the version badge's
  phone-width scenario is removed. OpenSpec cannot drop a scenario through MODIFIED, so the
  version badge requirement is removed and re-added, unchanged otherwise, as "The header
  shows the panel version and its update state".
- `player-stats`: the "Players section is usable on a phone" requirement is removed.

## Impact

- `web/src/styles.css`: `.app-main` max width, the map table's cell wrapping, the header
  comment, and removal of the `max-width: 520px` media query.
- `web/src/test/shell.test.tsx` and `web/src/test/players.test.tsx`: the phone-layout
  assertions become desktop-layout assertions.
- No API, backend or data changes.
