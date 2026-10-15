# Tasks

## 1. Desktop width

- [x] 1.1 In `web/src/styles.css`, change `.app-main` to `max-width: 1280px` (design D1). In `web/src/test/shell.test.tsx`, replace the "wrap at a 375px viewport" test with a desktop-layout test asserting `.app-main` has `max-width: 1280px`; keep its header-wrap and version-badge assertions, since they still protect a narrow desktop window. Verify `npm --prefix web test` passes.
- [x] 1.2 Remove the `@media (max-width: 520px)` block and rewrite the stylesheet's header comment from "Mobile-first ... 375px" to a desktop statement (design D3). Extend the desktop-layout test to assert no `max-width: 520px` media query remains. Verify `npm --prefix web test` passes.
- [x] 1.3 In `web/src/test/players.test.tsx`, rename the "the phone layout (7.4)" block to a narrow-window block and leave its table-scroll and dialog assertions as they are. Verify `npm --prefix web test` passes, and that `grep -rn -i "phone\|375px" web/src` finds nothing outside the iOS input-font comments.

## 2. Maps file table fits

- [x] 2.1 In `web/src/components/MapTable.tsx`, give the Map and Package cells a wrapping class, and in `styles.css` let that class wrap (`white-space: normal`, `overflow-wrap: anywhere`) while the Size, Played, Frags and Actions cells stay `nowrap` (design D2). Verify with a test in `web/src/test/maps.test.tsx` that both text cells carry the class, and with a stylesheet assertion in the desktop-layout test that the class wraps and `.row-actions` and `td.num` do not.
- [x] 2.2 Run `npm --prefix web run lint` and `npm --prefix web run build`; verify both pass.

## 3. Integration

- [x] 3.1 Run the full Python suite (`.venv/bin/python -m pytest`); verify it passes. The bundle served by the panel is rebuilt, but no backend code changes.
- [x] 3.2 On the test panel (10.0.1.147), upload a map package with a long file name. Open Maps, then Files, in a browser window at least 1280px wide. Verify the content is 1280px wide, the uploaded map's row shows Download and Delete, and `.map-table`'s `scrollWidth` does not exceed its `.table-scroll`'s `clientWidth`. Then narrow the window to about 1000px and verify only the table box scrolls, not the page. Delete the test package afterwards.
- [x] 3.3 Open Dashboard, Settings, Players, Console and Panel at 1280px and verify nothing overflows or looks broken at the wider width (cards grid, forms, dialogs).

## Workflow follow-up

- Add a CHANGELOG entry with the next version bump: the panel is desktop-only and wider, and the Maps Files table no longer scrolls sideways.
- Archive the change once reviewed, syncing the `web-ui-shell` and `player-stats` deltas into the main specs.
