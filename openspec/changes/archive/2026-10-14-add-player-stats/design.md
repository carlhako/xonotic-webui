# Design

## Context

See `proposal.md` for motivation and scope. The requirements are in
`specs/player-stats`, `specs/server-settings` and `specs/server-console`.

How the relevant parts of the panel work today:

- **Line flow.** The supervisor's stdout pump calls `console.add_output(line)` (the buffer,
  whose listener is `Console._on_line`) and then one `LineSink`, which is
  `StatusTracker.on_line`, set with `set_line_sink`.
  `events.parse_event` recognises `:gamestart`, `:join`, `:name` and `:part`, and ignores
  everything else.
- **Panel queries.** `Console.query(command, collector)` sends a command without echoing
  it, under the command lock, and withholds the lines the collector consumes from clients
  and from replay. The tracker uses it for `status 1` and `sv_eventlog`.
- **Forced cvars.** `serversettings/registry.FORCED_CVARS` is written to the end of the
  wrapper config at every start. `RESERVED_CVARS`, derived from it, is refused by
  settings and raw overrides.
- **State.** Everything persistent lives under `STATE_DIR`, owned by the service user
  (`ProtectSystem=strict` with `ReadWritePaths` on it). Paths derive from `Settings`
  properties such as `state_file` and `game_settings_file`.
- **Frontend.** Sections register in `web/src/sections.tsx`. Data comes from
  `useResource`, the status SSE context, and `ColoredText` for names. There is no modal
  component yet. `Confirm` is inline.

### Spike findings (local 0.8.6 dedicated server plus a headless SDL client, 2026-10-14)

Captured as the existing fixtures were (see `tests/fixtures/xonotic/README.md`), with the
report target set to `-`, two bots and one human client. The game source behind each
finding is the 0.8.6 `qcsrc`.

1. **`sv_cmd who`** (`CommonCommand_who`) lists every slot with
   `ent  nickname  ping  pl  time  ip  crypto_id`. When run from the server console,
   `caller` is null, so `sv_status_privacy` does not mask anything. `who "|"` uses `|` as
   the column separator:

   ```
   ^7List of client information:
   ^7|^7ent |^7nickname            |^7ping |^7pl |^7time     |^7ip              |^7crypto_id|^7
   ^7|^7#1  |^7^1Spike^7Tester         |^733   |^70  |^700:00:27 |^7127.0.0.1       |^7dRXbACYQr56HZ6KBw0zOIi7K1hQ3sUdDvO+DxBuUlSA=|^7
   ^7|^7#2  |^7[BOT]Eureka         |^70    |^70  |^700:00:27 |^7null/botclient  |^7null/botclient|^7
   ^7Finished listing 3 client(s) out of 16 slots.
   ```

   - The nickname is cut to 20 characters. The fingerprint is base64 (`+`, `/`, `=`, never
     `|` or space) and matched the client's `key_0-public-fp.txt`.
   - Clients generate their key on first run. An unsigned key (`ID-Is-Signed: no`) is
     still stable, and still proven by possession of the secret key.
   - The engine also logs `Authenticated connection to <ip:port> ... client is <fp>@...`,
     but that is keyed by address and port, not slot, so it is not used.

2. **`:kill`** (`LogDeath`) is
   `:kill:<mode>:<killer pid>:<victim pid>:type=<deathtype>:items=...[:victimitems=...]`,
   with mode `frag`, `tk`, `suicide` or `accident`. Suicides and accidents carry the
   victim as the killer. Captured:
   `:kill:frag:2:3:type=258:items=2-1:victimitems=2-1`.

3. **Report** (`PlayerStats_GameReport`). With `g_playerstats_gamereport_uri -`,
   `url_fputs` prints each report line as it is written. That happens synchronously, so
   the report is one contiguous block, and the map vote is not delayed. It is sent at
   match end (`finished`) and from world shutdown (map change or quit, `!finished`). A
   crash sends nothing.

   Captured block, printed between `:end` and `:gameover`:

   ```
   V 9 / R xonotic-v0.8.6 / G dm / O Xonotic / M atelier / I 0.1791943205.451290 /
   S <hostname> / C 0 / U 26999 / D 180.03 / L
   P <fingerprint | bot#<skill>#<name> | player#<pid>>   i <pid>   [n <name>]   [t <team>]   r <0|1>
   e <event> <value>   ...   (non-zero values only)
   <blank line>
   ```

   - The events are `alivetime`, `avglatency`, `wins`, `matches`, `joins`, `rank`,
     `scoreboardpos`, `scoreboardvalid`, `scoreboard-<label>`, `total-<label>`,
     `acc-<weapon>-{hit,fired,cnt-hit,cnt-fired,frags}`, `achievement-<name>` and
     `kills-<pid>`.
   - `n` appears only if the player allows uid2name (default: ask). Bots always have it.
   - `P` is the fingerprint only if the player allows uidtracking (default on).
     Otherwise it is `player#<pid>`.
   - `i` is always the match's player id.

4. **Map change** (captured). Every connected client, bots included, gets a fresh `:join`
   with a **new player id** on the same slot. Ids restart per map, since `playerid_last`
   lives in progs. Bots are also renamed. No `:part` is logged for the change.

5. **Default target.** `g_playerstats_gamereport_uri` defaults to
   `https://stats.xonotic.org/stats/submit`. `url_multi_fopen` treats a list as failover,
   not fan-out, so the report cannot go to both XonStat and the console.

### Capture results (task 1.1, 2026-10-14)

The three things the spike inferred from source are now captured as fixtures
(`tests/fixtures/xonotic/`), and confirm the above, with these additions:

6. **`:kill` shapes.** `frag`, `tk`, `suicide` and `accident` are all
   `:kill:<mode>:<killer>:<victim>:type=...:items=...`. `type` is a number for weapon deaths
   and a name (`KILL`, `HURTTRIGGER`) for special ones. A `suicide` caused by one's own weapon
   splash has a numeric type. Item codes can end in a flag letter (`T`, `S`).
   - A `tk` only happens with real friendly fire. The default (`g_friendlyfire_virtual 1`)
     applies none, so default servers rarely log one.
7. **A finished match versus a cut-short one.**
   - `gotomap` and `endmatch` end the match normally: the report is printed after `:end` and
     before `:gameover`, and carries `matches` (and `wins` for the winner).
   - `changelevel` and a quit send the report from world shutdown: no `:end` or `:gameover`
     around it, no `matches`, no `wins`. The report is printed immediately before the next
     map's `:gamestart:`.
   - `matches` and `wins` are only written for a player with a valid scoreboard position, so a
     spectator in a finished match has neither. `finished` is therefore "some player has
     `matches`".
   - A quit right after a map start prints an empty report (`D 0`, no `P` blocks). Nothing is
     stored for it.
8. **Map change.** Every client gets a fresh `:join` with a new id on the same slot, bots
   first and the human after. A human's re-join is preceded by `is connecting...` lines and
   followed by the fingerprint being available to `who` again, unchanged.
9. **A client lost while the next map loads gets no `:part`.** The server logs
   `Client "<name>" dropped` and nothing else, because the client never re-joined, so it has no
   player id in the new match. A later `:part` for an id belongs to a client that did re-join.
   This is exactly the case D3's grace period closes.
10. **Privacy opt-out.** A client with `cl_allow_uidtracking 0` is `P player#<id>` in the
    report and has no `n` line with `cl_allow_uid2name 0`, but `who` still reports its
    fingerprint. D6 therefore links by `i`, never by the `P` value.
11. **Report extras.** Team games add `Q team#<id>` lines (each team's `e` lines follow it)
    and `t <id>` on every player. `anticheat-*` events appear for humans and are ignored.
12. **`who`.** A nickname is cut to 20 visible characters (colour codes are kept but not
    counted), and may contain `|`.

## Goals / Non-Goals

**Goals:**

- One recorder fed by the existing line flow, with no extra process, no log files to
  tail, and no new runtime dependency.
- Per-match rows as the source of truth, with totals computed at read time. Comparisons
  and time windows later are then queries, not migrations.
- Live counts within a few seconds, without writing to SQLite on every kill.
- Nothing in recording can block the event loop or the game server.

**Non-Goals:**

- Honouring the client's `cl_allow_uidtracking` opt-out. `who` cannot see it, so it
  could only be inferred after the fact (a `player#<pid>` report key for a player whose
  fingerprint is known). That is a later change if wanted.
- Merging or reconciling a player recorded by name with the same person later recorded by
  key.
- Deriving weapons from `:kill` `type=` numbers. Weapon statistics come from the report,
  which names weapons.
- Counting warmup separately. Kills during warmup are counted like any other.

## Decisions

### D1. The recorder is a second line consumer, alongside the tracker

`Supervisor.set_line_sink` becomes `add_line_sink`, a list called in order, each guarded
like the change listeners. The tracker and a new `players.PlayerRecorder` both register.
The recorder parses with `events.parse_event`, extended with `PlayerKill(mode,
killer_id, victim_id)`, and with its own report parser.

- **Rejected: the tracker forwards events to the recorder.** It couples status
  reconciliation, which rebuilds the roster from `status 1` and invents no events, to
  history. It would also hide the report lines, which are not events.
- **Rejected: a separate log reader** (`sv_eventlog` files). It needs a second path into
  the userdir, file rotation and offsets, and gains nothing.

### D2. Identity: one `who` lookup per burst of joins

When a human `:join` arrives, the recorder creates a **participant** in memory, keyed by
the match's player id and holding the slot, the raw name and the bot flag. It then
schedules a lookup:

- **Batching.** The lookup runs about 100 ms later, so that the burst of re-joins on a
  map change produces one query. It runs `console.query('who "|"', WhoReplyCollector())`.
  The collector starts at `List of client information` and ends at
  `Finished listing N client(s)`, so the reply is withheld like any panel query.
- **Parsing a row.** Rows are split on `|` after colour stripping, taking fields **from
  the right**: the last non-empty field is the fingerprint and the one before it is the
  address. A name containing `|` therefore cannot shift them. The slot comes from the
  leading `#<ent>`.
- **Bad values.** An empty fingerprint, `null/botclient` or `hidden` all mean "none".
- **Resolved key.** `fp:<fingerprint>` if there is one, otherwise
  `name:<colour-stripped name>`. Bots never query and are keyed `bot:<stripped name>`.
  The participant then gets or creates its `players` row.
- **No answer.** On `InternalQueryError` or `NotRunningError`, every pending participant
  falls back to its name key. The spec allows that per visit.
- **Before resolution.** Kills that arrive before resolution are added to the
  participant in memory and written once it has a player row (see D4).

The reconciling `status 1` used by the tracker does not cover this, because it has no
fingerprint column.

### D3. Sessions survive map changes by slot and key

A session belongs to a slot while it is open. The rules:

- **Map change.** On `:gamestart`, every open session is marked *awaiting rejoin*, with
  the gamestart time noted. A `:join` on that slot that resolves to the same key clears
  the mark and continues the session.
- **Rejoin never comes.** A different key, a `:part`, or no rejoin within a 120 s grace
  period (map load plus a slow client) closes the session. The end time is the part
  time, or for a lapsed grace the gamestart time.
- **Server stops.** The recorder subscribes to supervisor state, as the tracker does. A
  transition to `stopped` or `starting` closes every open session at that moment.
- **Panel exits while sessions are open.** A clean shutdown closes them, since the game
  is stopped too. After a panel crash, start-up closes any sessions still open, at their
  player's `last_seen`, which each flush updates (D4). Time on server is therefore never
  counted while the panel isn't running.

### D4. Write-behind with a short flush interval

- **In memory.** Live counters (frags, deaths, suicides, team kills) and session
  `last_seen` accumulate on the participants.
- **Flushing.** A flush task writes the dirty state every 2 s. It also flushes at once on
  `:gamestart`, after a report, on server stop and on panel shutdown. One flush is one
  transaction.
- **Revision.** Each committed flush bumps an in-memory `revision`, which the API uses
  (D7).
- **What a panel crash loses.** At most 2 s of live counts. The game is unaffected.

### D5. SQLite store: per-match rows, aggregated on read

The store is `STATE_DIR/players.db`, a new `Settings.players_db` property. It runs in WAL
mode with one connection used from a single worker thread through `asyncio.to_thread`,
serialised by a lock, so no database call ever runs on the event loop. The schema
version is `PRAGMA user_version`, with forward-only migrations in code.

```
players      (id PK, key UNIQUE, is_bot, name, first_seen, last_seen)
aliases      (player_id, name, first_used, last_used, PK(player_id, name))
matches      (id PK, match_id UNIQUE, map, gametype, started_at, duration,
              finished NULL|0|1, reported 0|1)
sessions     (id PK, player_id, started_at, ended_at NULL)
match_players(match_pk, player_id, PK(match_pk, player_id),
              frags, deaths, suicides, teamkills,            -- live, from :kill
              score, kills, alivetime, dmg, dmgtaken, wins,  -- report
              rank, avglatency, scoreboard_valid, joined)
weapon_stats (match_pk, player_id, weapon, frags, hit, fired, cnt_hit, cnt_fired,
              PK(match_pk, player_id, weapon))
achievements (match_pk, player_id, name, count, PK(...))
extra_stats  (match_pk, player_id, name, value)   -- other scoreboard-* labels, e.g. caps
```

- **Times** are UTC epoch seconds. The browser formats them, as the web-ui-shell spec
  requires.
- **Live and report columns sit side by side**, so the two sources never double count:
  frags, deaths and suicides come only from `:kill`, and everything else only from the
  report. The report's `scoreboard-kills` is kept in `kills` as a cross-check, never
  shown as frags.
- **Gametype-specific labels** (caps, returns, laps) go to `extra_stats`. The schema
  then doesn't track every gametype, and the dialog can list whatever exists.
- **Totals** are one `GROUP BY player_id` query joined to the sums of `sessions`. An open
  session counts up to now.
- **Formulas.** K/D is `frags / max(deaths, 1)`. Accuracy is `sum(hit) / sum(fired)`
  over all weapons, the damage-weighted figure the game's own accuracy display uses.
  It is `null` when nothing was fired.
- **Indexes** on `match_players(player_id)`, `sessions(player_id)` and
  `aliases(name)`. That keeps a list query over tens of thousands of players fast
  enough for a 5 s poll.
- **Rejected: running totals on `players`.** Cheaper to read, but it loses per-match
  history, which the comparison and time-window refinements need.
- **Rejected: JSON files like `settings.json`.** Unbounded growth, and a rewrite on every
  flush.

**As built** (differences from the text above, found while implementing):

- The lookup command is `sv_cmd who "|"`, the form that was captured. Plain `who` was not tried.
- `player_totals` caches each player's per-match sums, refreshed in the transaction of any
  write that touches the player. The per-match rows stay the source of truth, and the cache
  is rebuilt from them. Without it a 20,000-player list took about 110 ms (aggregating on
  every read); with it, under 100 ms with room to spare. Time on server adds the open
  sessions at read time, so it is never stale.
- `players` and `aliases` carry a colour-stripped, case-folded `plain` column, used for
  sorting by name and for the search.
- A flush updates `last_seen` for open sessions at most every 30 s, not on every flush, so a
  server full of bots does not write every 2 s. A panel crash therefore leaves a session
  closed up to 30 s early at start-up.
- The shown name is the alias with the latest `last_used`; a name noted late never replaces a
  more recent one.

### D6. Linking the report to players

The parser is a small state machine:

- **Start.** A block starts at a line matching `^V \d+$` after colour stripping.
- **Body.** Header letters (`R G O M I S C U D L`), `P`/`i`/`n`/`t`/`r` player lines,
  `Q` team lines and `e <event> <number>` lines all belong to the block.
- **End.** A blank line ends it. Any other line also ends it and is passed through, so
  a malformed block cannot swallow the console.

Applying a complete report:

- **Which match.** `I` must equal the current match's id from `:gamestart`. If not (for
  example the panel started mid-match), the report is applied to a match row created
  from its own `M`, `G` and `I`.
- **Which player.** Each `P` block's `i <pid>` is looked up in that match's participant
  table, which includes participants who have already left. The `P` key itself is
  ignored for identity. That makes uidtracking opt-outs and bots work the same as
  everyone else.
- **No participant.** A `pid` with no participant (the join happened before the panel
  started) is matched by fingerprint if `P` is one. Otherwise it is recorded against
  `name:<n>` when `n` is present, and skipped with a log line if not.
- **Finished or not.** The `matches` event is present only when the match finished, so
  `matches.finished` comes from that. `wins` comes from the `wins` event.

The participant table for a match is released after its report is applied, or at the
next `:gamestart` plus the grace period from D3.

### D7. Report lines are withheld through a standing console filter

`Console` gains `add_filter(filter)` for unsolicited blocks. The filter is fed every
`OUTPUT` line before fan-out, exactly like a pending query's collector, and its consumed
lines join `_suppressed_seqs`. `StatsReportFilter` reuses the D6 recogniser and only
says *consumed or not*. The recorder parses its own copy from the sink, so the console
never depends on the recorder.

### D8. The report target is a forced cvar

`("g_playerstats_gamereport_uri", "-")` is appended to `FORCED_CVARS`. It is then:

- written last in the wrapper config at every start
- reserved against settings and raw overrides (the `server-settings` delta)
- read by the game when it sends each report, so it holds from the first match

The read-only cvar catalogue shows it as reserved with no extra work.
`g_playerstats_playerbasic_uri`, the Elo fetch behind `Receiving player stats failed`,
is left alone.

### D9. API

The API has two routes, with pydantic models in `api/schemas.py`:

- **`GET /api/players`** takes `sort` (a fixed list of column names), `order`
  (`asc`/`desc`), `q` (name search), `bots` (bool), `limit` (default 50, max 200) and
  `offset`.
  - It returns `{revision, total, players: [...]}`, where each row is the spec's totals
    plus `id`, `name`, `plain_name` and `is_bot`.
  - Search matches any alias, colour-stripped, using `LIKE` with escaping, and ignores
    case.
  - Sorting is done in SQL with a fixed column whitelist, never interpolated from
    input, and ties break on `id`.
  - It sends `ETag: "<revision>-<query hash>"`. A matching `If-None-Match` gets `304`,
    so an idle table's 5 s poll costs almost nothing.
- **`GET /api/players/{id}`** returns:
  - the totals, plus `first_seen`, `last_seen` and `aliases`
  - `sessions` (count) and `key_prefix` (the first 8 characters of the fingerprint, or
    null)
  - `damage` (dealt and taken) and `avg_latency`
  - `weapons` (per weapon: frags, hit, fired, cnt_hit, cnt_fired, accuracy)
  - `achievements` and `extra` (summed `extra_stats`)
  - `has_match_stats`
  - `404 player_not_found` for an unknown id

The full fingerprint is never sent to the browser.

Paging and server-side sorting are needed because a public server builds up thousands of
one-visit players. Sending them all on every poll would be megabytes.

### D10. Web: Players section, table and dialog

- **Section.** `{ path: "/players", label: "Players", element: <Players /> }` in
  `sections.tsx`.
- **State.** Sort, order, search (debounced 250 ms), the bots toggle and the page are
  kept in the URL query string. Reloading or sharing a link then restores the view, and
  the refresh keeps it.
- **Refresh.** `usePlayers` polls every 5 s while `document.visibilityState` is
  `visible`. It sends `If-None-Match` and keeps the previous rows on screen while the
  next page loads.
  - **Rejected: an SSE stream of player changes.** It adds a broadcast path for little
    gain at a 2 s flush granularity.
- **Table.** Column headers are `<button>`s carrying `aria-sort`. The table sits in an
  `overflow-x: auto` wrapper, which the spec allows on phones. Names render through
  `ColoredText`. Durations format as `18h 2m`, last seen as relative time with the
  absolute local time in `title`.
- **Dialog.** A new `components/Dialog.tsx` wraps the native `<dialog>` with
  `showModal()`, which gives Escape, focus trapping and `::backdrop` for free. A close
  button and a backdrop click also close it.
  - Rows are activatable by click or by Enter/Space, as a `role="button"` cell link.
  - Loading the detail uses `useResource`.
  - On narrow screens the dialog is `width: min(40rem, 100vw - 2rem)` with an internal
    scroll.

## Risks / Trade-offs

- **[Only some formats are verified]** `tk`, `suicide` and `accident` lines, a report
  with a playing human, and leaving during a map change are inferred from source, not
  captured. → Task 1 captures them as fixtures before parsing code is written. Every
  parser ignores what it doesn't recognise rather than failing.
- **[Name fallback merges strangers]** Players without a key who share a name, above all
  the default `Player`, become one history. → Real clients almost always have a key. The
  fallback applies only when the lookup fails or no key is reported. Accepted.
- **[A failed lookup splits one person]** A visit recorded under a name key stays apart
  from the same person's key history. → Lookups are local console round trips, which
  rarely fail. Merging is a named non-goal.
- **[XonStat submission stops]** This is operator-visible and was accepted. → It is
  stated in the proposal, the changelog entry and the README.
- **[The report is lost on a crash]** → Live counts and sessions are unaffected. The
  match row stays `reported = 0`.
- **[Unbounded growth]** History is kept forever. → Rows are small (a busy server adds
  well under 1 MB a day), and the indexes keep list queries fast. Retention is a later
  change if ever needed.
- **[The withheld report hides game output from the operator]** → It is also not
  printed in plain game logs today. The data is in the Players section, and only blocks
  that parse as a report are withheld.

## Migration Plan

1. On upgrade, the first start creates `players.db` at schema version 1. There is no
   history from before the upgrade.
2. The next server start writes the new forced cvar. A running server is not touched
   until it restarts. The panel's upgrade already restarts the game, so in practice the
   report target changes with the upgrade.
3. Rollback: an older panel ignores `players.db` and no longer forces the cvar, so
   XonStat submission resumes at the next start. Re-upgrading reuses the existing
   database.
