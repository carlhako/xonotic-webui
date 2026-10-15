# Xonotic fixtures

Real console output captured from the unmodified Xonotic **0.8.6** dedicated server
(`xonotic-linux64-dedicated`, build 03:14:05 Jun 20 2023), not hand-written. Humans were a
real `xonotic-linux64-sdl` client run headless (`SDL_VIDEODRIVER=offscreen`,
`LIBGL_ALWAYS_SOFTWARE=1`); bots came from `bot_number N`.

The server was launched as the supervisor launches it:

    xonotic-linux64-dedicated -userdir <dir> +port <p> +sys_colortranslation 2 \
        +serverconfig xonotic-webui.cfg

where `xonotic-webui.cfg` is `exec server.cfg` followed by the event-log cvars (see design.md
D3). Each line is exactly as the server printed it (including the leading `^7`).

| file | what it is |
| --- | --- |
| `startup.txt` | process start through the first `:gamestart:` / `:gameinfo:end` |
| `status_premap.txt` | `status` reply while the server is still in `_init/_init` (not ready) |
| `status1_empty.txt` | `status 1` with no players |
| `status1_one_human.txt` | `status 1` with one human whose name has colour codes |
| `status1_humans_bots_v6.txt` | `status 1` with two humans (one over IPv6) and a bot |
| `status_two_line_humans_bots.txt` | plain `status` (two lines per player, names truncated) |
| `match_end_next_map.txt` | `:scores` / `:gameover` then the next `:gamestart` |
| `session_humans_only.txt` | whole run: join, rename, part, no bots |
| `session_humans_bots_v6.txt` | whole run: two humans (IPv4 and IPv6), a bot, rename, parts, match end |
| `session_ansi_translated.txt` | whole run with the engine's default ANSI colour translation (`sys_colortranslation` not set) |
| `who_reply.txt` | `sv_cmd who "|"` from the server console: two humans (one nickname containing `\|` and cut to 20 characters) and two bots |
| `kill_variants.txt` | one `:kill:` line per shape: `frag`, `tk`, `suicide` (a `KILL` and a weapon death type) and `accident`, with and without item flags |
| `report_finished.txt` | the end of a match (`:scores` to `:gameover`) with `g_playerstats_gamereport_uri -`: a human who fired two weapons, two bots, `wins`, `matches`, achievements |
| `report_unfinished.txt` | the report printed by `changelevel` (a match cut short): no `:end`, no `matches`, no `wins`, and the next `:gamestart:` straight after the blank line |
| `report_privacy_optout.txt` | a finished-match report for a human who allows neither uidtracking nor uid2name: `P player#1`, no `n` line |
| `session_map_change_rejoin.txt` | whole run: a human and a bot, `who`, a `changelevel` with the human connected (every client re-joins with a new id, no `:part`), `who` again, an accident, quit |
| `session_leave_during_map_change.txt` | whole run: a `gotomap` match end, and the human's client closed while the next map loads: `Client ... dropped` and no `:part` for it |
| `cvarlist.txt` | full `cvarlist` reply (6,097 cvars: `name is "value" ["default"] description`), source of the bundled cvar catalogue |

The player-statistics files (`who_reply.txt` onwards) were captured for the `add-player-stats`
change with `g_playerstats_gamereport_uri "-"`, `sv_spectate 0` (a joining client plays at once)
and `bot_number` set, with a headless client whose `autoexec.cfg` set `cl_allow_uid2name 1` and
`cl_welcome 0` (otherwise a dialog takes the keyboard) and used `defer` to hold `+fire`, `+left`
and `+forward` and to `kill` itself. Team kills needed real friendly fire (`teamplay_mode 2`,
`g_friendlyfire_virtual 0`) in `tdm`, and accidents came from bots on `afterslime`.

## Transcripts (`transcripts/`)

Captured for the `config-and-maps` change (see its `design.md`, **Spike findings**) on an
empty server, no clients. Unlike the files above these are annotated: each line is
`<seconds since spawn> <line>`, `>>> ` marks a command written to stdin, and a `#` header
records the config files in effect (the wrapper `exec`s `xonotic-webui-settings.cfg` where
the run used one). Local paths are replaced with `<game>` and `<userdir>`.

| file | what it shows |
| --- | --- |
| `cvars_gametype_gotomap_paused.txt` | cvar reads, live `timelimit`, `maxplayers` refusal, `gametype`, `gotomap` stalling on an auto-paused server |
| `changelevel_overrides_gametype.txt` | `*_override` limits surviving `changelevel`/`restart`, per-gametype limit precedence, unsupported-map fallback to dm, `resetmatch` |
| `generated_settings_cfg_unpaused.txt` | settings from a generated cfg at startup; `endmatch` and `gotomap` with `sv_autopause 0` |
| `autopause_unpause_actions.txt` | auto-pause on: queued `endmatch`/`gotomap` completed by a console `pause` toggle; re-pause on the new map |
| `value_escaping_maxplayers_mutators.txt` | `;`, `$`, `\"`, `//` in quoted values (cfg and stdin); `maxplayers` via `changelevel` vs `map`; mutator at next map |

## Live match state (`match_*.txt`)

Captured for the `add-live-match` change on the test LXC (0.8.6, the panel's real
`sv_eventlog` setup) by sending the poll the panel sends (`openspec/changes/add-live-match/design.md`
D1) through `POST /api/console/command` and reading `GET /api/console/stream`. Lines are as
the server printed them, with the leading `^7`; the command itself is not in the files. A
human played or spectated and `bot_number 2` gave two bots.

| file | what it is |
| --- | --- |
| `match_dm_live.txt` | deathmatch mid-match: the globals, `timelimit`, `fraglimit`, `status 1` and `sv_cmd printstats` with a `:player:` line for the human and each bot |
| `match_dm_spectator_live.txt` | the same with the human spectating: their `:player:` line has `spectator` in the team field and `status 1` shows `-666` frags |
| `match_tdm_live.txt` | team deathmatch: team numbers 5 (red) and 14 (blue), `:labels:teamscores:` and a `:teamscores:` line for every team slot 1-15 |
| `match_ctf_live.txt` | capture the flag, a spectator and two bots: the extra columns (`caps!`, `fckills`, `returns`, `drops<`, `pickups`, `captime<`) and `caps!!,score` team labels |
| `match_intermission_live.txt` | the reply while the match-over scoreboard is showing (`intermission_running` 1) |
| `match_clock_cases.txt` | annotated blocks (`# ===== case =====`) of the clock queries only, with `:player:` and empty `:teamscores:` lines removed: warmup, countdown, playing, a raised limit, intermission and an autopaused server |

What the captures showed (the design's D1, D3 and D5 were amended to match):

* **The dump leaves out bots by default.** `sv_logscores_bots` is 0, so only humans have a
  `:player:` line. The poll sets it to 1 for the dump and back (`sv_logscores_bots 1; ...;
  sv_cmd printstats; sv_logscores_bots 0`). The `_live` fixtures were captured that way.
* **The live `:player:` line has no ent**: `:player:see-labels:<values>:<playtime>:<team>:<name>`.
  The end-of-match dump the game prints itself (`:scores:`) has one more field, `<team>:<ent>:<name>`.
  Players are joined to `status 1` rows by name.
* **Teams and spectators.** `<team>` is `-1` (no team), `5` red, `14` blue, or the word
  `spectator`. A spectator keeps the score values they had and `status 1` gives them `-666`
  frags. `:teamscores:` is printed for every slot 1-15; a slot nobody is on has no values.
* **The dump is printed regardless of `sv_eventlog` and `sv_eventlog_console`** (both set to 0
  in turn): `:status:` ... `:end` and `stats dumped.` still arrive.
* **Intermission** shows `intermission_running 1` and `game_stopped 1`, and the dump still
  lists every client with the final scores.
* **Warmup** (`g_warmup 1`, `g_warmup_limit 60`): `warmup_stage 1`, `game_starttime 0`,
  `warmup_limit 60`; warmup ended when `time` reached the limit. After it the server printed
  `Match is restarting...` and `:restart`, and `game_starttime` was set ahead of `time` (70
  when `time` was about 60 at the restart), so a countdown follows warmup.
* **Countdown** after a map load: `time` is about 2.5s ahead of wall time since the load
  (the load itself), `game_starttime` is 16 with `g_start_delay 15`.
* **Raised limit.** `sv_cmd extendmatchtime` added 5 minutes: `timelimit` read
  `"15.000001"`, so the cvar is a float.
* **Autopause** (`sv_autopause 1`, nobody connected, a map freshly loaded): `time` stayed at
  `6.00009537` across three readings 9 seconds apart. A server that was already running
  when the last human left keeps running: the pause only happens after a map start.
* **`timeout_status`** read 0 in every capture and is not part of the poll (it is in
  `match_clock_cases.txt` only).
* **Unknown global**: `No global 'nosuchglobal' in server!`.
* **Not captured**: overtime. Two attempts (`bot_nofire 1`, `timelimit 1`, a 0-0 tie) both
  ended the match at the limit with `checkrules_overtimesadded` still 0, so the overtime
  fields are unconfirmed on a real server.
