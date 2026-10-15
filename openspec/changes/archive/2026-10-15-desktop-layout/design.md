# Design

## Context

Every section renders inside `<main class="app-main">`, which `web/src/styles.css` caps at
`max-width: 960px` with a 16px side gutter. The stylesheet's header declares a mobile-first
contract (nothing may force sideways scrolling at 375px), and one `@media (max-width: 520px)`
block exists only for phones. Two frontend tests enforce the phone contract by reading the
stylesheet, since jsdom has no layout: `shell.test.tsx` ("wrap at a 375px viewport") and
`players.test.tsx` ("the phone layout (7.4)").

The Files view on Maps is `MapTable`, a `.data-table` inside a `.table-scroll` box inside a
`.panel`. Every `.data-table` cell is `white-space: nowrap`, so the table is as wide as its
longest map title, package name and set of row actions together.

Measured on the 0.4.0 test panel in a 1024px window:

```
 .app-main            960   (16px padding each side)
   .panel             928   (16px padding + 1px border each side)
     .table-scroll    892   (1px border each side)
       .map-table    1070   game maps only: Go to this map, Add to rotation
                     1232   with an uploaded map: + Download, Delete (+161px)

 at max-width 1280:  1280 - 32 - 34 - 2 = 1212px for the table   < 1232
```

So widening to 1280px alone still leaves a sideways scroll of about 20px once uploaded maps
are installed, and more with long package names.

## Goals / Non-Goals

**Goals:**

- Content 1280px wide on every section.
- The Maps Files table fits at that width, uploaded maps included, with room for longer
  package names than the ones measured.
- Phone-only CSS and tests removed, and defensive narrow-window rules kept.

**Non-Goals:**

- Re-laying out sections to use the extra width, for example a two-column dashboard.
- Changing other tables (Players, Raw cvars), which keep `nowrap` cells.
- Touching `index.html`'s viewport meta tag or the 16px input font sizes. Both are harmless
  on desktop, and removing them is churn with no benefit.

## Decisions

### D1: One width for every section

`.app-main` goes from `max-width: 960px` to `max-width: 1280px`. Nothing else in the shell
changes.

- *Alternative: widen only Maps* (a per-route class on `<main>`). Rejected, because the
  header and content edges would jump when switching sections, and the dashboard's coming
  scoreboard wants the width too.
- *Alternative: 1320px*, which fits the measured table without wrapping. Rejected, because
  the operator chose 1280, and wrapping (D2) is needed anyway for package names longer
  than the ones measured.

### D2: Text cells in the map table wrap; numbers and actions do not

Only in `.map-table`, the Map and Package cells allow wrapping (`white-space: normal`,
long tokens broken with `overflow-wrap: anywhere`), so a long title, internal name, package
name or the "restart the server to use this map" badge wraps instead of widening the table.
The Size, Played and Frags cells and the row's actions stay `nowrap`, because a split
number or a stack of buttons reads worse than a wrapped name. The table's fixed part is
then the numbers, the actions and the star, which is well under 1212px, and the two text
columns share the rest.

- *Alternative: icon-only or overflow-menu actions.* Rejected, because the labelled buttons
  are clearer, and the rest of the interface uses labelled buttons.
- *Alternative: wrap the actions onto two lines.* Rejected, because it makes rows of
  uneven height, and the buttons are the part of a row people aim at.

The cells are targeted by column in CSS or given a class in `MapTable.tsx`. Either is fine.
A class is more robust if a column is ever reordered, so prefer it.

### D3: Drop phone-only rules, keep narrow-window defences

Removed:

- the `@media (max-width: 520px)` block
- the "mobile-first, 375px" wording in the stylesheet header, which becomes a desktop
  statement

Kept, because a desktop window can still be narrower than 1280px, and long names exist at
any width:

- `.table-scroll` scrolling inside its own box
- `body { overflow-x: hidden }`
- `overflow-wrap: anywhere` on names
- the wrapping header
- dialogs sized with `min(40rem, 100vw - 2rem)`

These are what web-ui-shell's "Narrower desktop window" scenario relies on.

### D4: Tests assert the stylesheet, as they do today

jsdom cannot measure layout, so the tests keep reading `styles.css`:

- `shell.test.tsx`: the 375px test becomes a desktop-layout test. `.app-main` has
  `max-width: 1280px`, the map table's text cells may wrap, its number and action cells do
  not, and no `max-width: 520px` media query remains.
- `players.test.tsx`: the "phone layout (7.4)" block is renamed to a narrow-window block.
  Its table-scroll and dialog assertions still hold under the new requirement and stay as
  they are.
- `maps.test.tsx`: the Map and Package cells carry the wrap class, if D2 uses one.

The real check is a manual measurement on the test panel (see tasks): with an uploaded map
installed, `.map-table`'s `scrollWidth` must not exceed its box's `clientWidth` in a window
1280px or wider.

## Risks / Trade-offs

- [The browser window is exactly 1280px, so the vertical scrollbar leaves about 1265px] →
  D2's wrapping absorbs the difference: the text columns get narrower and wrap sooner, and
  nothing scrolls.
- [Prose on Settings and Panel runs to long lines at 1280px] → form inputs are already
  capped (`min(24rem, 100%)`). If the help text reads badly, cap paragraph width in a
  follow-up rather than narrowing the page.
- [Someone does open the panel on a phone] → it still loads. The page does not scroll
  sideways, and tables scroll in their box. Spacing is no longer tuned for it.

## Migration Plan

This is a frontend-only change and ships in the next release with the rebuilt static
bundle. There is no data, config or API change. Rollback is reverting the commit, or
upgrading to the following release.
