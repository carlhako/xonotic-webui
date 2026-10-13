# Design

## Context

See `proposal.md` for motivation and scope. This builds on the bootstrap change
(`bootstrap-xonotic-webui`), whose design decisions are referred to as B-D1..B-D16.

The relevant pieces as built:

- The supervisor launches the server with `+serverconfig xonotic-webui.cfg`, a wrapper it
  rewrites on every start: `exec server.cfg`, then the forced event-log and colour cvars
  (B-D3). This is the hook for panel-owned settings.
- `Console.query(command, collector)` sends a command on the panel's behalf and withholds
  the reply lines from clients. Withheld lines still pass through the console's history
  buffer, which holds `console_buffer_lines` lines (default 2000). The list of withheld
  line numbers is capped at 1024 and trimmed back to the newest 512.
- The status tracker parses `:gamestart:<gametype>_<map>` and already reports the map and
  gametype.
- The game version is pinned to 0.8.6 (B-D13), so facts about the game's cvars and
  commands are stable.

Every behavioural claim below about the game was verified against the unmodified 0.8.6
dedicated server in a spike, unless it is marked *unverified*. The source tree shipped in
the release zip (`source/qcsrc`, `source/darkplaces`) was read to explain the
observations. The facts are recorded under **Spike findings** and the captured output is in
`tests/fixtures/xonotic/`.

## Goals / Non-Goals

**Goals:**

- Settings persist across server and panel restarts, independently of `server.cfg`.
- Saving a setting tells the operator truthfully when it takes effect.
- Going to a map and skipping both work on an empty server while idle auto-pause stays on.
- Nothing an operator types into a settings field can execute a console command.

**Non-Goals:**

- Parsing or round-tripping `server.cfg` (beyond the read-only scan in D11).
- A per-gametype profile of limits (the game's own `g_<gametype>_point_limit` cvars remain
  available as raw overrides).
- Showing the server's pause state in status. The panel cannot query it (see D10), and
  this design only needs to undo the pause.

## Decisions

### D1. A second panel-owned config, executed between `server.cfg` and the forced cvars

The panel stores settings in `STATE_DIR/settings.json`, which is the source of truth. From
it, the panel generates `userdir/data/<APP_NAME>-settings.cfg`. The wrapper becomes:

```
exec server.cfg                     // operator's hand edits
exec xonotic-webui-settings.cfg     // generated from settings.json
sv_eventlog 1 ...                   // forced, unchanged (B-D3)
```

The file is regenerated on every save and on every start, atomically, like the wrapper.
Its name derives from `APP_NAME` (B-D16).

Ordering gives the precedence:

- Panel settings win over `server.cfg`.
- The forced cvars win over everything, so no setting can break the event log.

The cvars the panel forces, plus `port` (owned by panel settings, B-D6), are **reserved**.
A raw override of a reserved cvar is refused. `rcon_password` is also refused, because
this change does not handle secrets.

*Alternatives:* editing `server.cfg` in place (rejected: it would mean round-tripping
comments, aliases and conditionals the panel does not understand); applying settings only
over stdin (rejected: lost on restart).

### D2. Every setting carries an apply class

Each curated setting is a static registry entry in the backend: cvar, type, bounds or
choices, default, label, help text and **apply class**. The frontend renders the curated
tabs from this metadata, served by the API, so there is a single source.

| class | meaning | verified examples |
| --- | --- | --- |
| `now` | sent live; affects the running match | `hostname`, `timelimit`/`fraglimit` (current match), `bot_number`, `skill` |
| `next_map` | accepted live, takes effect when the next map loads | `g_<gametype>` / `gametype`, mutators (`g_instagib`), `g_maplist`, `*_override` limits |
| `next_start` | needs a `map` reload or a server restart | `maxplayers` (`changelevel` does not apply it; `map` and restart do) |

Saving a setting writes it to the store, regenerates the config and, if the server is
running, sends the value live. The response reports each key's class, so the UI can say
"applied", "applies at the next map" or "applies when the server restarts". A
`next_start` setting offers the existing restart action, which already asks for
confirmation when players are connected.

Raw overrides have no known class. They are sent live and reported as "may need a map
change or restart". They are written after the curated settings, so one that names a
curated cvar wins. Removing an override sends nothing: the running server keeps its value
until it next starts.

Resetting a curated setting to its default (`null`) sends the value the server would have
after a restart: what `server.cfg` sets, otherwise the game's default.

Live values are sent as ordinary console lines and echoed into the console history, as
operator commands are. Operators can see what the panel did to their server.

### D3. Limits are written as the game's override cvars

At every map load, the map's settings reset `timelimit` and `fraglimit`. A limit survives
only when written through an override cvar. Resolution happens once per map: the
per-gametype limit (`g_tdm_point_limit`, `capturelimit_override` for CTF, …) is tried
first, then the generic `fraglimit_override` / `leadlimit_override` /
`timelimit_override`. The first value `>= 0` wins, and `-1` means "use the map's default".

The curated **time**, **score** and **lead** limits therefore write `timelimit_override`,
`fraglimit_override` and `leadlimit_override`. Their default is `-1`, shown as "map
default". The per-gametype cvars default to `-1` (except Onslaught), so the generic
override reaches every gametype unless an operator sets a per-gametype cvar as a raw
override. That cvar wins, which the spike confirmed.

When the server is running and the value is `>= 0`, the plain cvar (`timelimit`,
`fraglimit`, `leadlimit`) is also sent live, so the current match changes too. Setting a
limit back to `-1` cannot restore the map default mid-match, so it is reported as
`next_map`.

"Score" means frags, captures or points depending on the gametype. The UI labels it with
the current gametype's unit and shows it next to the gametype selector.

### D4. Values are validated, then quoted and escaped

Verified console parsing rules:

- `;` inside double quotes does **not** split commands, in a config file or over stdin.
- `//` inside quotes is literal.
- `$name` **expands** inside quotes; `$$` is a literal `$`.
- `\"` is a literal quote.
- An unquoted value is cut at the first space.

The rules the panel applies:

- **Cvar names** must match `^[A-Za-z_][A-Za-z0-9_.]*$`.
- **Values**:
  - must be one line, of at most 1000 characters
  - must not contain control characters, `"` or `\`
  - colour codes (`^1`, `^xRGB`) are allowed
- **Serialisation**: every value is written as `name "value"`, with each `$` doubled.
  `set` is used for raw overrides so an unknown cvar is created.

Serialisation is one function used for both the generated config and live lines. It is
covered by tests with the hostile inputs above and checked once against the real server.

*Alternative:* escaping `"` and `\` instead of refusing them (rejected: no real setting
needs them and the escape rules are engine-specific).

### D5. Cvar catalogue: bundled, with live values fetched on demand

A full `cvarlist` reply is 6,097 lines (`name is "value" ["default"] description`). Sent
through `Console.query`, it would push the operator's whole 2,000-line console history out
of the buffer, and overflow the 1,024-entry list of withheld lines, which keeps only the
newest 512. Some older withheld reply lines would then be replayed to newly connecting
clients. So the panel never queries the full list at runtime.

Instead:

- **Static catalogue.** Generated at build time from the captured 0.8.6 `cvarlist` and
  shipped in the package: name, default and description. It works while the server is
  stopped, and is valid because the game version is pinned. `rcon_password` (shown masked
  as `********` by the game) and reserved cvars are marked as not editable.
- **Live values** for the cvars currently displayed (a page of search results, or the
  curated settings) come from one query that sends their names on one line separated by
  `;`. A collector expects one `"name" is "value" ["default"]` line or one
  `Unknown command "name"` line per name. This is a few dozen lines at most.

Raw overrides accept any valid name, including cvars not in the catalogue (mods, custom
aliases).

*Alternatives:* a stdout tap below the console buffer for one-off dumps (rejected: new
plumbing to avoid a problem the static catalogue removes); a much larger buffer (rejected:
it only moves the limit).

### D6. Map catalogue read from `.pk3` packages

The panel scans `<game_root>/data/*.pk3` and `<userdir>/data/*.pk3` (zip files), reading
the standard library's `zipfile` directory only:

- `maps/<name>.bsp` makes a map.
- `maps/<name>.mapinfo` gives `title`, `description`, `author`, the `gametype <id>` (or
  older `type <id>`) lines, and `hidden`.
- `maps/<name>.jpg|png` is the preview image, streamed from the zip by an endpoint.

Rules:

- A map in the user directory shadows one of the same name in the game tree.
- Hidden maps and names starting with `_` (e.g. `_hudsetup`) are excluded.
- The catalogue is cached and rebuilt when any package's size or modification time changes.
- A map with no `.mapinfo` in its package is listed with unknown gametypes and is not
  offered for any gametype, until the game has run once. It then writes a generated map
  information file, which the catalogue reads instead (verified, see Spike findings: the
  path is `userdir/data/data/maps/autogenerated/<name>.mapinfo`). A map that ships a
  `.mapinfo` is never overridden by a generated one.

The stock install has 30 maps, every one with a preview image. The server's own `lsmaps`
agreed with the parse (18 maps for dm).

### D7. Gametype is persisted as cvars, changed live with the command

The `gametype` command cannot appear in a config file ("This command works only when the
server is running"). The current gametype is just the cvar set to `1`, so the generated
config writes `g_<id> 1` and `0` for every other gametype. All 20 gametype cvars exist in
0.8.6, listed in a static registry: id, cvar, display name.

The UI offers only gametypes that at least one installed map supports.

When the server is running, the panel also sends `gametype <id>`. The game answers "Game
type successfully switched to tdm" and the change applies at the next map (`next_map`).
The game refuses a gametype that no installed map supports. The UI offers two ways to
switch:

- at the next map
- now, which also needs a map choice and then runs **go to map** (D9)

### D8. Rotation is `g_maplist` plus shuffle, filtered by gametype

The panel stores an ordered map list and writes `g_maplist "<maps>"` and
`g_maplist_shuffle 0|1`. An empty list writes no `g_maplist`, so the game's default applies
(all maps for the gametype). The shuffle flag is `null` until the operator chooses, and is
written whenever it has been chosen, even with an empty list, so "all maps, in order" is
possible.

Maps in the list that do not support the selected gametype are flagged in the UI and left
out of the generated value.

Voting is the curated `g_maplist_votable` (0 disables the vote) and
`g_maplist_votable_timeout`.

The game rewrites the live `g_maplist` (it shuffles it and fills it in when empty), so the
UI shows the stored list, never the game's working copy.

### D9. Match actions use the game's own commands

| action | command | with players | empty and unpaused |
| --- | --- | --- | --- |
| go to map | `gotomap <map>` | scoreboard (5 s), then that map; no vote | switch in ~1.3 s |
| skip | `endmatch` | scoreboard, then the map vote (up to `g_maplist_votable_timeout`) | next map in rotation in ~1.2–1.9 s |
| restart match | `restart` | immediate map reload | immediate |

Before `gotomap`, the panel checks the map against its catalogue and the current gametype,
and gives its own error. The game's error is misleading: a map that does not support the
current gametype gets "The map you suggested is not available on this server."

Only one action runs at a time; a second is rejected while one is pending.

Completion is the next `:gamestart:` the status tracker sees. The pending action, and its
outcome (succeeded / timed out), is published on the status stream, so every client sees
it. The timeout covers the scoreboard plus a full vote.

*Alternatives:*

- `changelevel` (rejected for actions: no scoreboard for connected players, and an
  unsupported map silently falls back to dm with "can't play the selected map in the given
  game mode (ctf). Falling back to a supported mode (dm).")
- the panel choosing the next map for skip (rejected: duplicates the game's rotation logic)

### D10. Idle auto-pause: unpause only to carry out an action

With the default `sv_autopause 1`, a dedicated server pauses 5 s after a map loads if
nobody is connected. It unpauses when a player joins. While paused, `gotomap` and
`endmatch` are accepted but wait indefinitely. `restart` and `changelevel` are not
affected. `sv_autopause` stays on by default and is exposed as a curated setting.

After sending `gotomap` or `endmatch`:

- **If no humans are connected**, the panel sends the engine's `pause` command through
  `Console.query`, so it never appears in the console. From the server console, `pause`
  toggles regardless of `pausable`, and the server reports the new state as
  `<name> unpaused the game` or `<name> paused the game`, where `<name>` is the hostname or
  `sv_adminnick`. The collector matches the suffix on stripped text.
  - "unpaused": the queued command runs on the next frame.
  - "paused": the server had been running (a human joined and left, or the map is under
    5 s old). The panel sends `pause` again to restore it.
- **If humans are connected**, the server is running and the panel does not send `pause`,
  so players never see a pause message.

The new map re-arms auto-pause. Verified: 17 s after a skip, the server had paused itself
again.

Pause state cannot be read directly (it is not a cvar and `status` does not show it),
which is why the panel toggles and reads the answer rather than checking first.

"No humans connected" comes from the status tracker's roster, so the roster has to be
right. A `status 1` reply that was produced before a join but applied after it used to
undo the join; the tracker now repeats the query (at most three times) when a join, part or
rename was seen while it was in flight.

The game command is sent before the unpause. If the unpause failed, the command stays
queued and runs when someone joins, and the action reports a timeout.

*Alternatives:* `sv_autopause 0` (rejected by the operator: idle CPU rose from 0% to about
1.5–2%); always toggling twice (rejected: it would broadcast pause messages to connected
players).

### D11. Settings that `server.cfg` also sets are flagged

The panel scans `server.cfg` for simple top-level lines (`name value`, `set name value`,
`seta name value`). Settings found there are marked "also set in server.cfg; the panel's
value wins". This is best-effort: `exec` lines, aliases and conditionals are not followed.

### D12. API

- `GET /api/settings`: curated settings with value, default, apply class, live value
  (when running) and the `server.cfg` flag.
- `PATCH /api/settings`: a partial update; returns each key's apply class.
- `GET /api/settings/overrides`, `PUT /api/settings/overrides/{name}`,
  `DELETE /api/settings/overrides/{name}`.
- `GET /api/cvars?q=&offset=&limit=`: the catalogue search, with live values for the
  returned page.
- `GET /api/gametypes`, `GET /api/maps`, `GET /api/maps/{name}/preview`.
- `PUT /api/gametype` `{gametype}`, `GET /api/rotation` and `PUT /api/rotation`
  `{maps, shuffle}`: the writes behind D7 and D8. A rotation names only installed maps; the
  response flags those the selected gametype cannot play.
- `POST /api/match/goto` `{map}`, `POST /api/match/skip`, `POST /api/match/restart`.
  The actions return `202` once the command is delivered (and an empty server has been
  unpaused, D10); the outcome arrives on the status stream (D9) as `status.action`.
- Validation errors are `422` with a stable `code` and, where one exists, the `field`
  (`invalid_setting`, `unknown_setting`, `reserved_cvar`, `invalid_cvar_name`,
  `unknown_gametype`, `gametype_unavailable`, `map_not_installed`,
  `map_unsupported_gametype`); a busy or stopped server is `409` (`action_in_progress`,
  `not_running`).

Settings can be written while the server is stopped. Actions return `not_running`, as
console commands do.

### D13. Frontend

- **Settings** section: tabs for Identity, Match, Bots, Voting, Mutators and Server,
  rendered from the registry metadata, plus a **Raw cvars** tab (catalogue search and the
  overrides list).
- **Maps** section: a map grid with previews and gametype badges, the gametype selector,
  the rotation editor, and "go to this map".
- **Dashboard**: Skip, Restart match and the pending-action indicator beside the existing
  lifecycle controls. Confirmation when humans are connected follows the existing stop and
  restart pattern.

### D14. Tests without the game

The fake server (B-D15) learns the following, driven by the new fixtures:

- cvar get/set
- `gametype`
- `gotomap`, `endmatch`, `restart`
- `pause`, with auto-pause semantics: paused 5 s after a map with no humans, and commands
  that wait while paused

Real-server checks go on the manual checklist.

## Risks / Trade-offs

- **A panel setting silently overrides `server.cfg`** → flagged in the UI (D11); the
  precedence is documented.
- **The pause probe briefly pauses a running empty server** (the "paused" answer), for one
  round trip → it is restored at once, and it happens only when no humans are connected.
- **A stored score limit may suit one gametype and not another** (30 frags vs 30 captures)
  → the limit is shown next to the gametype; per-gametype cvars remain available.
- **Skip does not decide the next map** when players vote → by design; go to map is the
  deterministic action.
- **The engine's console parsing differs from what was observed** → the serialiser rejects
  rather than escapes the uncertain characters; hostile-input tests; one real-server check.
- **`maxplayers` is not in the captured `cvarlist`** (it is read back with no default
  part), so the curated registry carries its default (16) itself and the "every curated cvar
  exists" check exempts it.
- **The static catalogue misses cvars from mods** → raw overrides accept any valid name.
- **Custom maps without mapinfo get no gametypes** → listed but not selectable; reading
  the generated mapinfo is a follow-up check.

## Migration Plan

An existing install has no `settings.json`. The generated config is then a header only,
so server behaviour is unchanged until the operator saves a setting. The wrapper gains one
`exec` line.

Rolling back to the bootstrap release rewrites the wrapper without that line on the next
start. The generated file is then ignored, and `settings.json` is kept for a later upgrade.

## Spike findings

Recorded from the 0.8.6 dedicated server (build 03:14:05 Jun 20 2023), launched as the
supervisor launches it. Captured output is in `tests/fixtures/xonotic/`.

**Reading and setting cvars**

- `<name>` alone replies `"<name>" is "<value>" ["<default>"]`. `maxplayers` replies with
  no default part.
- `cvarlist` lists 6,097 cvars, one per line as `name is "value" ["default"] description`,
  ending with `6097 cvar(s)`. `rcon_password` is shown as `********`.
- `cvarlist <prefix>` filters by prefix and ends `N cvars beginning with "<prefix>"`.
- `maxplayers N` while running prints "maxplayers can not be changed while a server is
  running. / It will be changed on next server startup ("map" command)." `changelevel`
  does not apply it; `map <name>` does.
- `g_instagib 1` applies at the next map: `:gameinfo:mutators:LIST:instagib:norecoil`.

**Limits**

- `timelimit 5` changes only the current match.
- `timelimit_override 3` / `fraglimit_override 7` gave `timelimit 3` / `fraglimit 7` on
  every later map.
- `g_tdm_point_limit 12` outranked `fraglimit_override 7` on tdm (`fraglimit 12`).

**Gametype and maps**

- `gametype tdm`: "Game type successfully switched to tdm"; applies at the next map.
  `gametype nosuch`: "Failed to switch to nosuch: this game type does not exist!".
  `gametype` with no argument prints usage. In a config file the command is refused, but
  `g_dm 0` / `g_tdm 1` works.
- `changelevel <map>` is immediate even while paused. An unsupported map falls back to dm
  with a warning.
- `restart` reloads the map at once and emits a new `:gamestart:`. `resetmatch` emits
  `:restart` (ignored by the status parser) and no `:gamestart:`.
- `gotomap <map>` sets `nextmap` and ends the match: "Map switch will happen after
  scoreboard." An unknown map, or one that does not support the gametype: "The map you
  suggested is not available on this server."
- `endmatch` is an alias for `_endmatch 1`. On an empty unpaused server the next map in
  `g_maplist` loaded about 1.2 s later. The match end emits `:scores:` … `:end`,
  `:gameover`, then `Switching to map <m>`.
- When `g_maplist` is empty the game fills it with all maps for the gametype, so the live
  value is not the operator's choice. With `g_maplist_shuffle 0` and a fixed list, the
  rotation followed the list in order.

**Auto-pause**

- With `sv_autopause 1` (default), an empty dedicated server pauses 5 s after a map loads
  and stays paused until a player joins (`Pause_TryPause_Dedicated`, deferred at world
  spawn). While paused, `gotomap`/`endmatch` waited at least 25 s with no effect.
- `pause` from the server console toggles and broadcasts `<hostname> unpaused the game` /
  `<hostname> paused the game`. Unpausing let a queued `endmatch` complete (next map 1.9 s
  later), and the new map paused itself again.
- Idle CPU (from `status`'s `timing:` line): 0.0% paused, about 1.4–1.9% unpaused.

**Console parsing** (config file and stdin alike)

- `"a;b"` stays one value; `"a;echo X"` did not run `echo`.
- `"x $hostname y"` expanded to the hostname; `"d$$d"` gave `d$d`; `"q\"q"` gave `q"q`;
  `"live // comment"` was literal; an unquoted `cfg ok` gave `cfg`.

**Other**

- The server tries to upload match stats to `stats.xonotic.org` by default
  (`g_playerstats_gamereport_uri`); with no players the upload fails with HTTP 422. This is
  exposed as a curated "report match stats" setting.
- Map catalogue: 30 stock maps, all with `.mapinfo` and `maps/<name>.jpg`.

**Verified on the real server after the change was built** (0.8.6 dedicated server from the
release zip, driven through the panel; the server needs a `server.cfg` in the user
directory or it quits a few seconds after start with "Dedicated server requires server.cfg")

- *Generated map information (task 4.2).* A `.bsp` with no `.mapinfo`, shipped in a user
  `.pk3`, got `userdir/data/data/maps/autogenerated/<name>.mapinfo` on the first start
  (note the doubled `data`, and that it is written by the server, not at install time).
  Its `title`, `description` and `author` come from the `.bsp`; its `gametype` lines are the
  gametypes the game itself will play the map in (for a copy of `boil.bsp`: `dm`, `duel`,
  `ka`, `lms`, `mayhem`, `surv`, `tmayhem`). The catalogue reads it (D6).
- *Value delivery (task 7.1).* `Welcome; have fun`, `$hostname rocks`, `^1Red ^xF80Server`,
  `a // b ... $$ q` written by the generated config and by live console lines read back
  verbatim (`$` doubled on the way in, literal on the way out) and no other command ran.
- *Idle auto-pause (task 7.2, empty server).* With `sv_autopause 1` and nobody connected:
  skip on a paused server completed in 2.2 s (one `pause`, answered "unpaused"); go to map in
  1.3 s (same); restart in 0.8 s with no `pause`. With the server empty but running (manually
  unpaused, as after a player left) skip completed in 1.5 s and the panel's two toggles
  answered "paused" then "unpaused". `sv_autopause` stayed `1`. The panel's own `pause`
  lines and commands never reached the console history clients are sent. *Not run:* the
  same actions with a client connected (no Linux client binary is shipped in the zip and the
  SDL build dependencies are not installed here).
- *Gametype ids.* Every `gametype` id in the 29 stock maps' `.mapinfo` is in the registry
  (`dm tdm lms ca ft ka kh dom duel ctf rc cts ons nb as`), and the generated file confirms
  `mayhem`, `surv` and `tmayhem`. `inv` and `tka` are unconfirmed (no stock map uses them).
- *Catalogue.* 30 stock maps (29 listed, `_hudsetup` excluded), all with a preview image.
