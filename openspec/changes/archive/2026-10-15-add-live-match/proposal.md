# Proposal

## Why

The dashboard shows which map is being played and who is connected, but not how the match
is going. An operator glancing at the panel cannot tell how long is left before the map
changes or who is winning, which is what they would see at a glance in the game. Both can
be read from the running server once a second without touching the game or the players.

## What Changes

- The dashboard shows a **match clock** like the game's HUD timer:
  - time left in the match
  - a countdown before the match starts
  - warmup
  - a count-up when there is no time limit
  - overtime
  - match over

  The clock freezes while the server is paused, for example autopaused with nobody
  connected.
- The dashboard shows the **full scoreboard** as the game does. It has one row per player
  with their name, ping, time played, and the score columns the game reports for the current
  gametype (score, kills, deaths, suicides, and extras such as captures). It is sorted the
  way the game sorts, with bots marked and spectators listed apart. Team games add a totals
  row for each team, in the team's colour. The score limit is shown beside the clock.
- The panel reads this from the server about once a second, and only while at least one
  browser has the dashboard open and the server is running. Clients receive it as a live
  stream, separate from the status stream, so other sections are not pushed an update every
  second.
- The polling is invisible: the commands and their replies never appear in the Console
  section.
- It degrades rather than fails:
  - When the scores cannot be read (the event log is unavailable), the clock still shows.
  - When the clock cannot be read, the scores still show.
  - When the server is stopped, neither is shown.

Out of scope:

- round timers in round-based gametypes (Clan Arena, Freeze Tag): the match clock only
- race and CTS lap times and records
- storing anything: the live view is read, shown and discarded (match history stays with
  player-stats)
- acting on the match from the scoreboard, such as kicking or moving players

## Capabilities

### New Capabilities

- `live-match`: the state of the match in progress, meaning its clock, limits and
  scoreboard. It covers how the panel reads it from the server, the live stream that serves
  it, and how the dashboard shows it.

### Modified Capabilities

None. The dashboard's existing state cards and controls are unchanged. The clock and
scoreboard are added beside them and specified in `live-match`.

## Impact

- New backend module for the poller and the score-dump parser, wired into the runtime.
  Two new endpoints: `GET /api/match` (snapshot) and `GET /api/match/stream` (SSE).
- `tests/fake_xonotic/server.py` learns `sv_cmd printstats` and `prvm_global`, with
  advancing server time and pausing. New real-server fixtures go in
  `tests/fixtures/xonotic/`.
- `web/openapi.json` and `web/src/api/schema.d.ts` are regenerated. The Dashboard gets a
  match clock and a scoreboard component.
- No new dependencies and no stored data. Nothing is added to the game's config. While the
  dashboard is open the poll raises `sv_logscores_bots` for the length of each score dump so
  that bots are listed, and puts the operator's value back.
- Lays out within the 1280px desktop layout, already in place from the archived
  `desktop-layout` change.
