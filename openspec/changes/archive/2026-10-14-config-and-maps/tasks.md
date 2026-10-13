# Tasks

Run the groups in order; each depends on the ones before it. Design decisions are cited as
D1–D14 (`design.md`); captured server output is in `tests/fixtures/xonotic/` (`cvarlist.txt`
and `transcripts/`).

## 1. Fake server: the new commands

- [x] 1.1 Extend `tests/fake_xonotic/server.py` with a cvar store: `<name>` replies `"<name>" is "<value>" ["<default>"]` (no default part for `maxplayers`), an unknown name replies `Unknown command "<name>"`, `<name> "<value>"` and `set <name> "<value>"` assign, and `;` outside quotes separates commands while `$$` reduces to `$`, as shown in `transcripts/value_escaping_maxplayers_mutators.txt`; verify with new cases in `tests/test_fake_server.py`
- [x] 1.2 Add map and gametype behaviour to the fake: a configurable installed map → gametypes table, `g_<id>` cvars selecting the gametype, `gametype <id>` with the real success and failure replies, `changelevel`/`restart` that emit `:gamestart:<gametype>_<map>:<id>`, and `maxplayers N` printing the real refusal text; verify fake-server tests against `transcripts/changelevel_overrides_gametype.txt`
- [x] 1.3 Add match-end behaviour to the fake: `endmatch` and `gotomap <map>` (with its three real replies) produce `:scores:`…`:end`, `:gameover`, `Switching to map <m>` and the next `:gamestart:` from a `g_maplist` rotation, with a scoreboard delay only while a human is connected; verify fake-server tests against `transcripts/generated_settings_cfg_unpaused.txt`
- [x] 1.4 Add auto-pause to the fake: with `sv_autopause 1` and no humans it pauses `autopause_delay` seconds after a map loads, queued `endmatch`/`gotomap` wait while paused, `pause` toggles and prints `<hostname> unpaused the game` / `<hostname> paused the game`, and `fake_join` of a human unpauses; verify fake-server tests reproducing `transcripts/autopause_unpause_actions.txt`

## 2. Settings core (server-settings)

- [x] 2.1 Implement cvar-name validation and the value serialiser (D4): reject newline, control characters, `"` and `\`; always quote; double every `$`; `set` form for raw overrides; verify unit tests with `Welcome; have fun`, `$hostname rocks`, `//`, colour codes and each rejected character, and a fake-server round trip showing the value arrives verbatim
- [x] 2.2 Add the static registries: curated settings (cvar, type, bounds or choices, default, label, help, apply class per D2, including the limits mapped to `*_override` cvars per D3, `sv_autopause` default on, and match-stats reporting), the 20 gametypes (id, cvar, name, score unit), and the reserved cvars (forced wrapper cvars, `port`, `rcon_password`); verify unit tests that every curated cvar and every gametype cvar exists in `tests/fixtures/xonotic/cvarlist.txt`
- [x] 2.3 Implement the settings store at `STATE_DIR/settings.json` (curated values, raw overrides, gametype, rotation; atomic write; a missing file means empty); verify tests for round trip, missing file and a corrupt file reported as an error without losing the file
- [x] 2.4 Generate `userdir/data/<APP_NAME>-settings.cfg` from the store on every save and every start, and add `exec <APP_NAME>-settings.cfg` to the wrapper between `exec server.cfg` and the forced cvars (D1); verify supervisor tests for the wrapper's line order, an empty store producing a header-only file, and a fake-server start honouring a saved hostname
- [x] 2.5 Implement the best-effort `server.cfg` scan for top-level `name value` / `set` / `seta` lines (D11); verify unit tests including comments, quoted values, `exec` lines and a missing file
- [x] 2.6 Implement saving: validate, refuse reserved cvars, persist, regenerate, and when running send each change live (limits also send the plain `timelimit`/`fraglimit`/`leadlimit` when `>= 0`, D3), echoed into the console history (D2); return the apply class per key (`next_start` when stopped, `next_map` for a limit set back to `-1`, "may need map change or restart" for raw overrides); verify tests with the fake server for each class, the stopped case, a reserved refusal and the echoed console lines
- [x] 2.7 Build the cvar catalogue (D5): a script that turns `tests/fixtures/xonotic/cvarlist.txt` into a packaged `cvars.json` (name, default, description; reserved and `rcon_password` marked not editable), plus a search over it; verify a test that the committed `cvars.json` matches the script's output and search tests by name and description
- [x] 2.8 Implement live values for a set of cvars as one panel query (names joined by `;`) with a collector expecting one `is` or `Unknown command` line per name (D5); verify tests that values come back, an unknown name is handled, a timeout raises, and the console history seen by clients is unchanged
- [x] 2.9 Update the README: a "Server settings" section (panel settings vs `server.cfg`, precedence, reserved cvars, when changes take effect) and the generated file and `settings.json` in "Where things live"; verify every path named matches the code's constants

## 3. Settings API

- [x] 3.1 Expose `GET /api/settings` (value, default, apply class, live value when running, `server.cfg` flag) and `PATCH /api/settings` (per-key apply class; validation and reserved errors with stable codes); verify API tests for running, stopped, out-of-range, reserved and injection-shaped input
- [x] 3.2 Expose `GET /api/settings/overrides`, `PUT`/`DELETE /api/settings/overrides/{name}` and `GET /api/cvars?q=&offset=&limit=` with live values for the returned page; verify API tests for add, change, remove, invalid name, reserved name and search while stopped and running
- [x] 3.3 Regenerate `web/openapi.json` and `web/src/api/schema.d.ts`; verify `tests/test_openapi_snapshot.py` passes and `npm run build` type-checks

## 4. Maps, gametype and rotation (map-control)

- [x] 4.1 Implement the `.pk3` map catalogue (D6): scan game and userdir packages, parse `.mapinfo` (title, description, author, `gametype`/`type`, `hidden`), find `maps/<name>.jpg|png`, userdir shadows the game tree, exclude hidden and `_` maps, cache keyed by package size and mtime; verify tests with small zip packages built in the test (including a map with no mapinfo and a shadowed map)
- [x] 4.2 Check on the real 0.8.6 server whether a map without `.mapinfo` gets a generated one under `userdir/data/maps/autogenerated/`; if so, read it in the catalogue, otherwise keep "unknown gametypes"; verify the finding is recorded in design.md (D6) and covered by a test
- [x] 4.3 Implement gametype selection (D7): persist it, write `g_<id> 1` and `0` for the others into the generated config, send `gametype <id>` when running, report `next_map`, and offer only gametypes with at least one installed map; verify tests with the fake server for selection, persistence across restart and the offered list
- [x] 4.4 Implement the rotation (D8): store the ordered list and shuffle flag, write `g_maplist` / `g_maplist_shuffle` (nothing when the list is empty), leave out and flag maps not supporting the gametype, report the stored list rather than the live cvar; verify tests including an incompatible map and the fake server following a fixed order

## 5. Match actions (map-control)

- [x] 5.1 Implement the action coordinator (D9): go to map (validated against catalogue and gametype with the panel's own errors), skip (`endmatch`) and restart match (`restart`); one action at a time; `not_running` when stopped; verify tests for each action, unknown and unsupported maps, a second action while pending and the stopped case
- [x] 5.2 Implement the auto-pause handling (D10): after `gotomap`/`endmatch`, when no humans are connected, send `pause` through the panel query path and send it again if the reply says "paused"; never with humans connected; verify fake-server tests for paused-empty, running-empty (joined and left), humans connected (no pause sent) and that no pause line reaches the console stream
- [x] 5.3 Track completion by the next `:gamestart:` with a timeout covering the scoreboard and a full map vote, and publish the pending action and its outcome in the status snapshot and stream; verify tests for success, timeout and a second client seeing the pending state
- [x] 5.4 Expose `GET /api/gametypes`, `GET /api/maps`, `GET /api/maps/{name}/preview`, `POST /api/match/goto`, `POST /api/match/skip` and `POST /api/match/restart` with stable error codes, then regenerate `web/openapi.json` and the TS types; verify API tests end to end with the fake server and the OpenAPI snapshot test
- [x] 5.5 Document map actions and idle auto-pause in the README (what skip and go to map do with and without players, why auto-pause stays on); verify the text matches the behaviour tested in 5.1–5.3

## 6. Web interface

- [x] 6.1 Add the Settings section to the section registry with tabs (Identity, Match, Bots, Voting, Mutators, Server) rendered from the API metadata: per-field validation errors, "applied / at next map / at restart" feedback after saving, the "also set in server.cfg" marker, a restart offer for next-start settings, controls disabled while disconnected; verify component tests for each feedback case and the marker
- [x] 6.2 Add the Raw cvars tab: catalogue search with defaults, descriptions and live values; the overrides list with add, edit and remove; reserved cvars read-only; verify component tests for search, add, remove and a reserved result
- [x] 6.3 Add the Maps section: a map grid with preview images and gametype badges, the gametype selector (at next map, or now with a map choice), the rotation editor (order, shuffle, incompatible maps flagged) and "go to this map"; verify component tests for filtering by gametype, an incompatible rotation entry and go-to-map
- [x] 6.4 Add Skip and Restart match to the dashboard with the pending-action indicator and outcome, and confirmation stating the human count when humans are connected (none otherwise), reusing the stop/restart confirmation; verify tests with and without players and for the pending, done and timed-out states
- [x] 6.5 Check the new sections at 375px width; verify no horizontal scroll with a screenshot check

## 7. Real-server verification

- [x] 7.1 On the real 0.8.6 server, confirm the serialiser's output in a settings cfg and over stdin leaves `;`, `$` and colour codes literal and runs no extra command; verify by recording the observed values in design.md's Spike findings
- [ ] 7.2 With idle auto-pause on and the real server empty and paused, run skip, go to map and restart match from the UI, then repeat with a headless client connected; verify each completes, the server re-pauses when empty, and the client sees no pause messages
- [x] 7.3 Walk every scenario in `specs/server-settings` and `specs/map-control` against the real server or the test suite, and run `openspec validate config-and-maps --strict`; verify none is unexercised and validation passes

## Workflow follow-up

- Archive `bootstrap-xonotic-webui` (once its remaining tasks are done) and then this change after review, so both sets of capabilities land in `openspec/specs/`.
