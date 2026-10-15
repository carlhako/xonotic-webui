# Tasks

Run the groups in order; each depends on the ones before it. Design decisions are cited as
D1–D8 (`design.md`). Backend tests go in `tests/`, frontend tests in `web/src/test/`.

## 1. Catalogue exposes the package (map-control)

- [x] 1.1 Add `package`, `package_size` and `pending_restart` to `MapEntry` in `src/xonotic_webui/maps/catalogue.py` and fill them from the owning package (D1); verify `tests/test_map_catalogue.py` cases for a user package, a game package, a package holding two maps, and a user map shadowing a game map reporting the user package
- [x] 1.2 Add the loaded-package snapshot (D5): record user package `(name, size, mtime_ns)` when the supervisor enters `STARTING`, and report `pending_restart` for a user package not in it while the state is not `STOPPED`; verify tests for upload-while-running (pending), the same upload while stopped (not pending), clear after a restart, and a deleted-then-reuploaded name (pending)
- [x] 1.3 Make `MatchActions.goto` reject a pending map with `MapNotLoadedError` (`map_needs_restart`, 422), ahead of the gametype check; verify `tests/test_map_control.py` cases for the rejection, that the current match is untouched, and that an already-loaded map still works
- [x] 1.4 Add `package`, `package_size`, `pending_restart` to `MapModel` and return them from `GET /api/maps`; verify `tests/test_api_maps.py` and that `web/openapi.json` / `web/src/api/schema.d.ts` are regenerated and `tests/test_openapi_snapshot.py` passes

## 2. Package store and upload validation (map-packages)

- [x] 2.1 Implement the package store module `src/xonotic_webui/maps/packages.py` with the file-name rule, the size limit, temp-file streaming, zip and map checks and the no-replace install via `os.link` (D3); verify unit tests with in-test zips for: valid, `.zip`/`.bsp`/no extension, `../x.pk3`, name with a space or leading dot, over 256 MB, not a zip, zip with no map, a map name starting with `_` only, member named `../x`, duplicate name, and no temp or partial file left in each failure
- [x] 2.2 Report duplicates in the result: maps in the upload whose name is already provided by another installed package; verify tests for a name matching a game map and a name matching another user package
- [x] 2.3 Clean stale `.upload-*.part` files in the user data directory at panel startup; verify a test that plants one and checks it is removed and `*.pk3` files are untouched
- [x] 2.4 Implement download and delete lookup (D4): validated name, regular file directly in the user data directory, never the game tree; verify tests for a user package, a game package name, `../`, an absolute path, an unknown name and a directory, all giving `package_not_found` without touching any file

## 3. Package API (map-packages)

- [x] 3.1 Add `PUT /api/packages/{filename}` streaming the raw request body into the store (D2), returning the maps found and duplicates, with stable error codes (`not_pk3`, `bad_filename`, `too_large` 413, `not_a_package`, `no_map`, `already_exists` 409); verify `tests/test_api_maps.py` (or a new `tests/test_api_packages.py`) cases for each error, a lying and a missing `Content-Length`, a client disconnect mid-body leaving nothing, and the new map appearing in `GET /api/maps` while the server is stopped and while running (pending)
- [x] 3.2 Add `GET /api/packages/{filename}` (attachment, byte-identical) and `DELETE /api/packages/{filename}` (returns the removed maps); verify API tests for the download bytes and `Content-Disposition`, delete removing the maps from the catalogue, a shadowed game map reappearing after the delete, and `package_not_found` for game packages and paths
- [x] 3.3 Regenerate `web/openapi.json` and `web/src/api/schema.d.ts`; verify `tests/test_openapi_snapshot.py` passes and `npm --prefix web run build` type-checks

## 4. Favourites (map-favourites)

- [x] 4.1 Implement the favourites store at `<state>/favourites.json` (D6): atomic write, a missing file is empty, a corrupt file is empty with a warning, names validated with `validate_name`, kept even when the map is not installed; add the `state_dir`-relative path to `Settings`; verify unit tests for round trip, missing, corrupt, duplicate add, remove of an absent name and an invalid name
- [x] 4.2 Add `GET /api/favourites`, `PUT /api/favourites/{map}` and `DELETE /api/favourites/{map}` under one lock; verify API tests including concurrent adds both surviving, persistence across a runtime restart, and working while the server is stopped
- [x] 4.3 Regenerate `web/openapi.json` and `web/src/api/schema.d.ts`; verify `tests/test_openapi_snapshot.py` passes

## 5. Maps section: views, table and filters (map-control, map-favourites)

- [x] 5.1 Add the API client methods (`uploadPackage`, `deletePackage`, `favourites`, `addFavourite`, `removeFavourite`) and a `useFavourites` hook with optimistic update and rollback; verify `web/src/test` cases for success and for a failed toggle restoring the star and showing the error
- [x] 5.2 Add the toolbar to `web/src/sections/Maps.tsx`: Cards | Files switch (both buttons on both views, choice kept in `localStorage` with try/catch) and the "Favourites only" toggle applied to both views and combined with the gametype filter; verify tests for switching, the choice surviving a remount, the filter applying across views, and the empty "no favourites yet" message
- [x] 5.3 Add the star to `MapCard` and implement `MapTable` (one row per map: star, title/name, package, size, Go to map, Add to rotation, Download, Delete) inside `.table-scroll`, sharing the `canGo`, `onGo` and `onAdd` of the card view; add the size formatter in `web/src/lib/`; verify tests that both views enable and disable Go to map identically (stopped server, wrong gametype, action pending, pending restart), that the confirmation appears with humans connected, that Add to rotation joins the draft, and that game maps show neither Download nor Delete
- [x] 5.4 Show `pending_restart` maps with a "restart the server to use this map" note and Go to map disabled in both views; verify a test for the note and the disabled button
- [x] 5.5 Style the toolbar, table, star and upload control in `web/src/styles.css`, including the phone width; verify with `npm --prefix web run build` and a check in the browser pane at 375 px

## 6. Upload and delete in the interface (map-packages)

- [x] 6.1 Add the upload control to the Files view: a file picker that only offers `.pk3`, a busy state, and on success a message naming the maps found, any same-name warnings and the restart note when the server is running, then reload the map list; verify tests for success, each API error showing its message, and a duplicate-name warning
- [x] 6.2 Add the delete popup using `Dialog`: names the file, lists its maps (from the map list), calls out maps in the rotation, deletes only on confirm; verify tests for confirm, cancel (nothing called), a map in the rotation being called out, and a failed delete showing the error and keeping the row
- [x] 6.3 Make Download a link to `/api/packages/{file}` with the `download` attribute; verify a test for the link target and that it is absent on game maps
- [x] 6.4 Disable upload, delete and download while the panel is disconnected; verify a test using the disconnected status

## 7. Docs and integration

- [x] 7.1 Update the README: Maps section (upload, Files view, favourites, restart needed for a new map, 256 MB limit, `.pk3` only) and the Security section (the panel now writes uploaded files; same trust boundary as the console; mention proxy body limits); verify `tests/test_readme.py` passes and every path named matches the code's constants
- [x] 7.2 Run the full suites: `pytest`, `ruff check`, `npm --prefix web run test` and `npm --prefix web run build`; verify all pass
- [x] 7.3 End-to-end in the browser pane against the fake server: upload a generated `.pk3`, see it listed with the restart note, restart the server, go to the map, star it, filter to favourites, download it, delete it with the popup; verify each step behaves as the specs state

## 8. Optional follow-up: live rescan (not required to ship)

- [x] 8.1 On a real 0.8.6 server, try `fs_rescan` after copying a package into the user data directory and record in `design.md` (D5) whether `gotomap` can reach the map and whether map information is generated; verify the finding is written down
- [x] 8.2 Only if 8.1 shows it works: issue `fs_rescan` after a successful upload while running and clear `pending_restart` for that package; verify tests with the fake server learning `fs_rescan` — Not applicable: 8.1 showed `fs_rescan` does not make `gotomap` reach the new map (see `design.md` D5), so nothing was added.

## Workflow follow-up

- Archive the change after review, syncing the delta specs into `openspec/specs/`.
