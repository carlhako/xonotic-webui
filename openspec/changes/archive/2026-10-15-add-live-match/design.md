# Design

## Context

The panel already talks to the game through its console:

- `Console.query(command, collector)` sends a command on the panel's behalf. Lines the
  collector consumes are withheld from clients and from replayed history.
- `StatusTracker` keeps map, gametype and roster from the event log, and publishes
  snapshots on an SSE stream.
- `StatsReportFilter` hides the end-of-match `V`/`P`/`e` report.
- Nothing parses the `:status:`/`:scores:`, `:labels:`, `:player:` or `:teamscores:` lines.
  `parse_event` ignores tags it does not know.

Probed on the real 0.8.6 server (test LXC, empty server autopaused):

```
 sv_cmd printstats                    :status:dm_bromine:6          <- gametype_map : rint(time)
                                      :labels:player:score!!,,,,...,kills,deaths<,,suicides<,dmg,dmgtaken<,rounds_pl,elo,,,
                                      :player:see-labels:<v,v,...>:<playtime>:<team>:<ent>:<name>   (one per client)
                                      :teamscores:see-labels:...    (team games; format unconfirmed)
                                      :end
                                      stats dumped.                 <- printed by the command itself
 prvm_global server time              time: 6.00009537
 prvm_global server game_starttime    game_starttime: 16            (g_start_delay 15)
 prvm_global server warmup_stage      warmup_stage: 0
 prvm_global server checkrules_overtimesadded   checkrules_overtimesadded: 0
 timelimit / fraglimit                "timelimit" is "10" ["0"]
```

Other facts from the probe:

- **Paused clock:** with no humans connected the server autopauses (`sv_autopause 1`) and
  `time` stops. That is why it read 6s though the map had been loaded for hours.
- **End-of-match format:** `report_finished.txt` shows the same `:labels:`/`:player:`
  format in the dump the game prints itself at match end, under `:scores:` instead of
  `:status:`.
- **Other game variables:** the progs also contain the globals `warmup_limit`,
  `intermission_running`, `game_stopped` and `timeout_status`.

## Goals / Non-Goals

**Goals:**

- One console round-trip per second while watched, invisible in the console.
- The panel needs no table of gametypes for the scoreboard: columns, their order and sort
  rules all come from the game's own `:labels:` line.
- Everything is read live each tick. No state is kept between panel restarts and nothing is
  stored.

**Non-Goals:**

- Interpolating the clock in the browser between server reads.
- Reading per-player state the dump does not carry, such as alive/dead or flag carrier.
- Supporting a game whose QC globals have other names. Such a game gets the scoreboard
  without the clock (D7).

## Decisions

### D1: One batched query per tick, terminated by `stats dumped.`

Each tick sends a single console line:

```
prvm_global server time; prvm_global server game_starttime; prvm_global server warmup_stage;
prvm_global server warmup_limit; prvm_global server checkrules_overtimesadded;
prvm_global server intermission_running; prvm_global server game_stopped; timelimit;
fraglimit; status 1; sv_cmd printstats
```

wrapped in `sv_logscores_bots 1; ...; sv_logscores_bots <original>`. The dump leaves out bots
unless that cvar is 1 (it is 0 by default), so it is raised for the length of the dump and
put back to the operator's own value, which the watcher reads once when polling starts
(`sv_logscores_bots`). Nothing is written to the generated config.

A `MatchReplyCollector` consumes the lines in order: the `name: value` global lines, the two
cvar lines, the `status 1` reply (for ping, reusing the row parsing in `events.py`), then the
dump from `:status:` to `:end`, and finally `stats dumped.`. That last line is printed by
the command itself even when the event log prints nothing, so it ends the reply
deterministically. The collector also consumes the error lines DarkPlaces prints for an
unknown global, so a missing global becomes "unknown" and does not leak into the console.

- *Alternative: separate queries per item.* Rejected: ten round-trips a second, each taking
  the command lock that operator commands also take.
- *Alternative: set `sv_logscores_bots 1` in the generated config.* Rejected: it is a
  persistent change to the game, and the game's own end-of-match dump would then list bots
  on the console.
- *Alternative: track the clock from event-log tags* (`:gamestart:`, `:startdelay_ended`,
  `:restart`). Rejected: it cannot recover after a panel restart mid-match, and it misses
  pauses and admin time changes. The globals give the game's own answer every tick.

### D2: The poller runs only while someone subscribes

A `MatchWatcher` owns an asyncio task that starts with the first subscriber of
`stream()` while the supervisor is `RUNNING`, and is cancelled when the last subscriber
leaves or the state leaves `RUNNING`. It mirrors `StatusTracker.stream()`: latest-wins
queues of size 1, and it publishes only when the snapshot dict differs from the last one
sent. The tick interval is 1s, measured from the start of each tick. A tick that is still
waiting for its reply delays the next tick rather than overlapping it.

The dashboard is the only subscriber. Opening it is what turns polling on.

### D3: The clock is computed on the server, in whole seconds

From one tick's values:

```
 intermission_running or game_stopped   -> phase ended
 warmup_stage                           -> phase warmup,  left = game_starttime + warmup_limit - time  (if warmup_limit > 0)
 time < game_starttime                  -> phase countdown, left = game_starttime - time
 else                                   -> phase playing / overtime (checkrules_overtimesadded > 0)
                                           elapsed = time - game_starttime
                                           left    = timelimit*60 - elapsed   (if timelimit > 0, floored at 0)
```

Values are rounded to whole seconds, so the snapshot changes once a second and the stream
pushes about once a second during play.

The warmup formula was confirmed on a real server (`g_warmup 1`, `g_warmup_limit 60`): during
warmup `game_starttime` is 0, so `left = warmup_limit - time`, and warmup ended as `time`
reached the limit. Overtime was not reproduced (a 0-0 tie at the limit ended the match with
`checkrules_overtimesadded` still 0), so the overtime phase follows the variable and is
covered by table tests only. At the match end both `intermission_running` and `game_stopped`
read 1. The cvar `timelimit` is a float (`"15.000001"` after `extendmatchtime`).

### D4: Paused is inferred from the server clock standing still

DarkPlaces does not expose its paused flag to the console, so the clock is reported as
paused when the server `time` has not advanced between two ticks at least 0.9s apart on the
panel's monotonic clock. The first tick after subscribing reports not paused. This covers
autopause, `pause` and anything else that stops game time. While paused, the snapshot does
not change and nothing is pushed.

### D5: The scoreboard comes straight from `:labels:`

The `:labels:player:` list gives column names by position. A name suffix gives its role:
`!!` marks the primary sort column, `!` the secondary, and `<` means lower is better. A
column is kept when:

- it has a name, and
- it is not `elo` or `rounds_pl`, which the game itself hides.

Each live `:player:` line is `<values>:<playtime>:<team>:<name>` with no ent. It is split
from the left into at most four fields, because the name comes last and may contain `:`.
`<team>` is a number, `-1` for none, or the word `spectator`. (The end-of-match dump the game
prints itself has an extra ent field; the panel does not parse it.)

Players are then sorted by primary, then secondary, then plain name, with the direction
taken from `<`. Values are numbers; fractional ones such as `dmg` are rounded for display in
the UI, not in the API. Bot status, ping and ent come from the `status 1` rows, joined on the plain name, taking
rows in order so two players with the same name are paired in the order the game lists
them.

Spectators are listed apart and without scores. The dump marks a spectator with the word
`spectator` in the team field, and they keep the values they had while playing, which are
not shown.

`:teamscores:` lines are parsed the same way against `:labels:teamscores:`. Team numbers map
to colours: 5 red, 14 blue, 13 yellow, 10 pink, and -1 means no team. Red and blue were
confirmed on a real server; yellow and pink follow the game's own table. The game prints a
`:teamscores:` line for each of the slots 1-15 and an empty one has no values, so only teams
with values are kept.

### D6: The score limit comes from `fraglimit` and the registry's unit

The value comes from the live `fraglimit` cvar, where 0 means no limit. The unit ("frags",
"captures", "points") comes from the existing `Gametype.score_unit` in
`serversettings/registry.py` for the gametype the event log reports. When the gametype is
unknown, the unit falls back to "points".

### D7: Each part degrades on its own

A snapshot is:

```
 Match {
   live: bool                      # false when not RUNNING or no map loaded yet
   map, gametype
   clock: { available, phase, paused, time_limit_s, left_s, elapsed_s, overtimes }
   score_limit: { value | null, unit }
   scoreboard: { available, columns[{key,label,primary,secondary,lower_is_better}],
                 players[{ent,name,plain_name,bot,ping,time_s,team,values{}}],
                 spectators[{ent,name,plain_name,bot}],
                 teams[{team,color,values{}}] }
 }
```

The parts are filled independently:

- **clock:** unavailable when `time` or `game_starttime` is missing.
- **scoreboard:** unavailable when no `:labels:player:` line arrived. On 0.8.6 the dump is
  printed even with `sv_eventlog 0`, so this covers a build that does not have the command.
- **query timeout:** keeps the previous snapshot.
- **`NotRunningError`, or the state leaving `RUNNING`:** publishes `live: false`.

### D8: Endpoints and UI

Endpoints:

- `GET /api/match` returns the current snapshot. It does not start polling.
- `GET /api/match/stream` is SSE and does start it.

Both go in a new `api/match.py` with pydantic models in `api/schemas.py`, plus a regenerated
OpenAPI file and TypeScript types.

UI:

- A `useMatch()` hook opens the stream only while the Dashboard is mounted.
- The Dashboard gets a clock card in the cards row:
  - **playing:** `6:40` plus `left · limit 10:00`
  - **other phases:** "Starting in 0:12", "Warmup", "Overtime", "Match over"
  - **paused:** a badge
  - **score limit:** shown beside the clock
- The **Scoreboard** panel replaces "Players online" while the scoreboard is available.
  It is a `.data-table` with columns:
  - #, Player (ColoredText), the game's columns, Ping, Time
  - team games: a coloured header row with the team totals above each team's players
  - spectators: a muted line underneath

  When the scoreboard is unavailable, the existing "Players online" list shows, with a note
  saying why.

## Risks / Trade-offs

- [`prvm_global` names are game internals and may change in a later Xonotic] → the clock
  is reported unavailable and the scoreboard keeps working (D7). The fixture tests pin the
  0.8.6 names.
- [Two pending queries that both accept `status 1` rows: the tracker's reconcile and the
  poll] → replies arrive in send order and each collector stops after its own reply, so
  they cannot swap. A test sends both back to back against the fake server.
- [A query a second competes with operator commands for the command lock] → the lock is
  only held while writing a line, never while waiting for the reply.
- [Raising `sv_logscores_bots` for the dump changes a cvar the operator may have set] → the
  watcher reads it once when polling starts and writes that value back in every tick, so
  the operator's value is what the game has between ticks and while nobody watches.
  If the read fails, `0`, the game's default, is used.
- [`printstats` also writes to the event-log file when `sv_eventlog_files` is on] → the
  panel does not enable that cvar. If an operator does, a line a second is the cost, and the
  risk is noted in the README.
- [`dmg` and time-valued columns have no unit in the dump] → numbers are shown rounded.
  Time-formatted columns such as fastest capture are left for a follow-up if they look
  wrong.
- [A dump line the parser cannot read] → it is skipped rather than failing the tick.
- [The dump during intermission] → it still lists every client with the final scores, so the
  scoreboard stays up under "Match over".

## Migration Plan

This is additive: no stored data, no config and no change to what is written to the game.
It ships in the next release. Rollback is upgrading or reverting, with nothing to clean up.

## Open Questions

- Should time-valued score columns (CTF fastest capture) be formatted as times? This is
  deferrable: they show as numbers until someone sees one in play.
