# Proposal

## Why

Adding a map today means copying a `.pk3` into the panel's user data directory by hand over
a shell, and removing one means the same. The Maps section can only browse stock-style
cards, so there is no plain list to see what is installed, how big each package is, or to
fetch a package back. Operators also have a handful of maps they use constantly and no way
to pick them out of a long catalogue. This change makes map packages manageable from the
panel and lets maps be starred.

## What Changes

- **Upload a map package** from the panel. Only a `.pk3` file is accepted (a `.zip` or any
  other type is refused). The upload is validated before it is installed: file name, size,
  that it opens as a package, and that it contains at least one map. A failed upload leaves
  nothing behind. A name that already exists is refused rather than replaced.
- **A second Maps view, "Files"**: a plain table with one row per installed map and no
  preview image. Columns are the map, the package file it comes from and that file's size.
  Each row keeps the **Go to map** and **Add to rotation** buttons.
- **View switch**: two small buttons at the top of the Maps section switch between the
  existing card view and the new table view. The Go to map and Add to rotation actions are
  available on both.
- **Delete a map package** from the table, behind an "are you sure" popup that names the
  file and every map in it. Only packages in the panel's user data directory can be deleted;
  the game's own packages are never touched.
- **Download a map package** from the table. Again user packages only.
- **Favourites**: a star button on every map card and every table row, and a "Favourites
  only" filter at the top that applies to both views. Favourites are stored by the panel,
  so every browser sees the same list.
- A newly uploaded map is listed immediately but the running game does not load a package
  added after it started, so it is marked as needing a server restart before it can be
  gone to. (Whether a live filesystem rescan can remove that restart is left as a follow-up
  once it has been tried on a real server; see `design.md`.)

Out of scope: unpacking or inspecting package contents beyond what validation needs;
replacing a package in place; uploading anything but `.pk3`; deleting or downloading the
game's own packages; ordering or grouping favourites; authentication (the panel remains
LAN-only and unauthenticated, and the README says so more strongly now that it accepts
uploads).

## Capabilities

### New Capabilities

- `map-packages`: installing, listing, downloading and deleting the map packages in the
  panel's user data directory, with upload validation and the restart-required state of a
  newly installed package.
- `map-favourites`: the persisted set of favourite maps, and the favourites filter shared by
  both Maps views.

### Modified Capabilities

- `map-control`: the installed-map list gains the package file and its size for each map,
  and the Maps section gains the second (table) view and the switch between the views,
  with go-to-map and add-to-rotation on both.

## Impact

- **Backend**: `src/xonotic_webui/maps/catalogue.py` records each map's package path and
  size; a new package store module handles upload, validation, delete and download; a new
  favourites store; new routes in `api/maps.py` (or a sibling router) and schemas; the
  generated OpenAPI document and TypeScript schema are regenerated.
- **Frontend**: `web/src/sections/Maps.tsx` gains the view switch, the table view, the
  upload control, the delete confirmation and the favourite stars and filter.
- **Dependencies**: none added (the upload is a streamed raw body, not multipart).
- **Docs**: README security section notes that the panel now writes uploaded files.
- **State**: a new `favourites.json` beside the panel's other state; uploaded packages go
  to the existing `<state>/userdir/data/`.
