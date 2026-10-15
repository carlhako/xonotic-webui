# Design

## Context

See `proposal.md` for motivation and scope, and `specs/` for the requirements.

The relevant pieces as built:

- The panel's state lives in `settings.state_dir`. The game's user directory is
  `<state>/userdir`, and its data directory `<state>/userdir/data` is where map packages
  already work: the catalogue globs `*.pk3` there and in the game tree, with the user
  directory taking precedence, and later file names beating earlier ones within a directory.
- `MapCatalogue` rebuilds itself when any package's size or mtime changes
  (`_signature_of`), so an uploaded or deleted package is noticed with no extra wiring. It
  already knows each map's owning package (`_Source.path`, `.origin`) but does not expose it.
- `MatchActions.goto` already validates the map against the catalogue and the effective
  gametype and raises `MapActionError` subclasses, which the maps router turns into 422s.
- The maps router, `RotationPanel` and `Maps.tsx` exist and carry the card view, the
  gametype filter and go/add actions. `Confirm` (inline) and `Dialog` (native modal) are in
  `web/src/components`.
- The panel has no authentication and binds to the LAN. Its API does not use multipart
  anywhere, and `python-multipart` is not a dependency.
- The game scans its packages once, at start. A package added later is invisible to
  `gotomap` until the server restarts (see D5 and Open Questions).

## Goals / Non-Goals

**Goals:**

- Keep the change small: reuse the catalogue as the single source of truth for what is
  installed, and add no dependency.
- A failed or interrupted upload can never leave a half-written or unusable file where the
  game would find it.
- The two Maps views and the favourites cannot disagree: one data source, one set of rules
  for Go to map.

**Non-Goals:**

- Inspecting or sanitising package contents beyond "is a package with a map in it". The
  panel is not a malware scanner and does not unpack packages.
- Replace-in-place, resumable uploads, upload progress beyond what `fetch` gives for free.
- Live reload of packages in the running game (deferred, see Open Questions).

## Decisions

### D1. The catalogue exposes the package; the table is built from `/api/maps`

`MapEntry` gains `package` (file name), `package_size` (bytes) and `pending_restart`
(D5). `source` ("game" | "user") already exists and decides whether download and delete are
offered. No separate "list packages" endpoint: the table has one row per map, a package's
maps are the entries sharing `package`, and the delete popup derives its map list from the
`/api/maps` data the page already holds.

*Alternative:* a `GET /api/packages` endpoint returning packages with their maps. Rejected:
a second source that must be kept in step with the catalogue, for data the page already has.

### D2. Upload is a streamed raw body, `PUT /api/packages/{filename}`

The browser sends the `File` as the request body (`fetch(url, {method: "PUT", body: file})`).
The server reads `request.stream()` chunk by chunk.

*Why not multipart:* FastAPI needs `python-multipart` for `UploadFile`, which is a new
runtime dependency for the installer to ship, and multipart parsers buffer or spool whole
files. A raw body also lets the size limit be enforced while streaming and lets the file name
be taken from the URL, which is validated the same way as on download and delete.

*Alternative:* multipart with `UploadFile`. Rejected for the dependency and spooling.

### D3. Validation, in order, all before anything is visible to the game

1. **File name** matches `^[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.pk3$` (lower-case extension; the
   catalogue's `*.pk3` glob is case-sensitive). The name is also used verbatim as the target
   file name, so no separator, space, leading dot or `..` can pass. Any other extension is
   its own error (`.zip`, `.bsp`, none) so the message says "only .pk3".
2. **Size**: refuse on `Content-Length` over 256 MB before reading, and count bytes while
   streaming (a missing or lying `Content-Length` is common) and abort at the limit.
3. **Stream to a temp file** in the same directory, `.upload-<random>.part` (not matched by
   `*.pk3`, so the catalogue and the game ignore it).
4. **Open as a zip** (`zipfile.ZipFile`) and read the member list only; nothing is
   extracted. Reject members with absolute names or `..` parts.
5. **Contains a map**: at least one `maps/<name>.bsp` with a name that does not start with
   `_` (the same rule the catalogue uses for internal maps).
6. **Install without replacing**: `os.link(temp, final)` then unlink the temp. `link` fails
   with `FileExistsError` if the name exists, which is the atomic no-overwrite check (a
   rename would silently replace). Any failure or exception unlinks the temp file.

The result lists the maps found and any whose name is already provided by another
installed package, so the operator is told when the upload shadows a game map or another
user package (the later file name wins among user packages, which is why the result says
"has the same name" rather than claiming to replace).

*Not done:* `ZipFile.testzip()` (reads and CRCs the whole file; the game reports a corrupt
member itself) and content scanning.

On startup the panel deletes stale `.upload-*.part` files, which only a crash can leave.

### D4. Download and delete use the same file lookup

Both resolve the file name (the same regex as D3) to `<userdir>/data/<name>` and require it
to exist as a regular file directly in that directory. Anything else, including a game
package name, a path or an unknown name, is the same 404 `package_not_found`; the game tree
is never searched, so stock packages cannot be reached. Download is a `FileResponse` with
`Content-Disposition: attachment`. Delete is `DELETE /api/packages/{filename}` and returns
the names of the maps that were in it. Deleting a file the running game has open is safe on
Linux (the unlinked file is released when the game closes it).

### D5. "Needs a restart" is a snapshot taken when the server starts

The catalogue keeps `_loaded`: the set of `(name, size, mtime_ns)` for user packages as
they were when the server last entered `STARTING` (it subscribes to the supervisor's state,
as `MatchActions` already does). While the state is not `STOPPED`, a user package whose key is
not in `_loaded` has `pending_restart = true`. While stopped nothing is pending, because
the next start loads whatever is there.

`MatchActions.goto` rejects such a map with a new `MapNotLoadedError` (code
`map_needs_restart`, 422) ahead of the gametype check, and the UI disables Go to map and
shows "restart the server to use this map".

*Alternative:* compare package mtime with the process start time. Rejected: it needs a
start time the supervisor does not expose, and it breaks on clock changes or a file
restored with an old mtime. The snapshot is exact about "what existed when the game
scanned".

**Finding (spike on a real 0.8.6 server, task 8.1): `fs_rescan` does not remove the
restart.** With the server running, a package holding a copy of `boil.bsp` under a new name
was placed in `userdir/data`, with and without a `.mapinfo` file:

- before `fs_rescan`, `gotomap <new map>` answers "The map you suggested is not available on
  this server.";
- `fs_rescan` prints nothing, and `gotomap <new map>` gives the same refusal afterwards, so
  the game's map list (built once at start) is not refreshed by it;
- the engine's own `changelevel <new map>` does load the map (the filesystem sees the new
  package), but the game then logs "Analyzing maps/... to generate initial mapinfo", bypasses
  its map list, and a following `gotomap` of a stock map was refused too (the server had to
  be restarted to recover). The panel does not use `changelevel`, and this state is worse than
  the restart it would save.

So the restart-required behaviour above is the final one; there is no live reload to add.

A package deleted while running disappears from the list at once; the running game may still
hold its maps in memory, which is harmless.

### D6. Favourites: a panel-owned file, keyed by map name

`<state>/favourites.json` = `{"maps": ["boil", ...]}`, written to a temp file and renamed (the
same pattern as the settings store). It is deliberately **not** in the server settings
store, which feeds the generated game config and carries "applies at next map" semantics.

API: `GET /api/favourites`, `PUT /api/favourites/{map}` (idempotent add),
`DELETE /api/favourites/{map}` (idempotent remove). The map name is validated with the
existing `validate_name` but need not be installed: favourites of an uninstalled map are
kept (the spec says they come back when the map is reinstalled) and simply filtered out of
the views. A corrupt or unreadable file is treated as empty with a logged warning rather
than an error: it is cosmetic data and must never block the Maps page. Read-modify-write is
under one `asyncio.Lock`.

*Alternative:* `localStorage`. Rejected: not shared between phone and desktop, which is the
point of a shared panel. It is still used for the two per-browser conveniences (D7).

### D7. Frontend: one data source, two renderers

`Maps.tsx` keeps its data hooks and gains a toolbar: the view switch (Cards | Files), the
"Favourites only" toggle and, on the Files view, the upload control. Both views receive the
same already-filtered list and the same `canGo(map)`, `onGo` and `onAdd` handlers, so the
rules in the `map-control` spec hold in both by construction. A new `MapTable` renders the
rows (map, package, size, star, Go to map, Add to rotation, Download, Delete) inside the
existing `.table-scroll` wrapper so it works on a phone.

- View and favourites-only are remembered per browser in `localStorage` (wrapped in
  try/catch, as the rest of the app does); the favourites themselves are server-side.
- Star toggles update optimistically and roll back with an error on failure.
- Delete opens the `Dialog` modal naming the file and its maps; maps in the rotation get a
  line of their own. Download is a plain link to `/api/packages/{file}` with the `download`
  attribute.
- Sizes are formatted in KB/MB with one decimal by a small shared helper.
- The OpenAPI document and generated `schema.d.ts` are regenerated from the backend.

### D8. Documentation

The README security section states that the panel now writes uploaded files and removes
them, and that this is as open as the console already is: do not expose the port.

## Risks / Trade-offs

- **Unauthenticated writes.** Anyone who can reach the port can fill the disk or install
  a package. → Same trust boundary as the console, which is already remote command
  execution on the game server; README says so. The 256 MB cap bounds a single upload, and
  a write failure (`ENOSPC`) cleans up the temp file and reports the error.
- **A package can carry server-side config.** A map's `maps/<name>.cfg` is executed by the
  game when the map loads. → Accepted, for the same reason; the operator chooses what to
  upload. Not scanned.
- **A restart is needed before a new map can be played.** → Shown clearly (D5); possibly
  removable (Open Questions).
- **Precedence among user packages is by file name.** `zzz.pk3` beats `mymap.pk3`. → The
  upload result reports duplicate names; deleting a package reveals the one it shadowed.
- **Large body through a proxy** (`client_max_body_size` etc.). → Documented in the README
  note; the panel itself is not behind one by default.
- **A slow or abandoned upload holds a connection.** → The temp file is removed when the
  stream errors or disconnects; uvicorn's own timeouts apply.

## Migration Plan

Additive: no data migration. `favourites.json` is created on first use. Rollback is
reverting the release; uploaded packages remain valid ordinary packages in the user data
directory.

## Open Questions

None. The `fs_rescan` question is answered in D5: it does not make a package added after
start usable by `gotomap`, so a restart stays required.
