# live-match Specification

## Purpose

Shows the operator how the match in progress is going, as a player would see it in the game: the match clock with its limits, and the live scoreboard, read from the running server about once a second while someone is watching.

## Requirements

### Requirement: Live match state is read only while someone is watching

The panel SHALL read the match state from the game server about once a second while at least one client is subscribed to the live match stream and the server is running. It SHALL stop reading when the last subscriber leaves or the server stops.

#### Scenario: Dashboard opened

- **WHEN** a client subscribes to the live match stream while the server is running
- **THEN** the panel starts reading the match state about once a second

#### Scenario: Nobody watching

- **WHEN** no client is subscribed to the live match stream
- **THEN** the panel sends the game server no match-state queries

#### Scenario: Server stops while watched

- **WHEN** the server stops while a client is subscribed
- **THEN** the panel stops querying it
- **AND** the client receives a state saying there is no match in progress

### Requirement: Live match state is streamed to clients

The panel SHALL provide the current match state as a snapshot and as a live stream that starts with the current state and then sends a new state whenever it changes. This stream SHALL be separate from the status stream.

#### Scenario: Client connects

- **WHEN** a client opens the live match stream
- **THEN** it immediately receives the current match state

#### Scenario: Nothing changes

- **WHEN** a read returns the same state as the last one sent, such as while the server is paused
- **THEN** no new state is sent

#### Scenario: Other sections

- **WHEN** a client has only the status stream open
- **THEN** it receives no per-second match updates

### Requirement: Match-state polling does not appear in the console

The commands the panel sends to read the match state, and the server's replies to them, SHALL NOT appear in the Console section or its replayed history.

#### Scenario: Console open beside the dashboard

- **WHEN** the dashboard and the Console section are both open while a match is played
- **THEN** the console shows no score dumps, clock queries or their replies

#### Scenario: The game prints a scoreboard itself

- **WHEN** the game prints its own end-of-match score dump to the console
- **THEN** that output is shown as it is today

### Requirement: The match clock follows the game's timer

The match state SHALL include a clock with the match phase, the time limit, and the time left or elapsed, computed from the server's own clock, the match start time and the live time limit, so that changes to the limit during a match are followed.

#### Scenario: Match in progress with a time limit

- **WHEN** a match with a 10-minute limit has been running for 3 minutes 20 seconds
- **THEN** the clock reports phase "playing" and 6 minutes 40 seconds left

#### Scenario: No time limit

- **WHEN** the time limit is 0
- **THEN** the clock reports the time elapsed since the match started and no time left

#### Scenario: Countdown before the match

- **WHEN** the map has loaded but the match start delay has not yet passed
- **THEN** the clock reports phase "countdown" and the seconds until the match starts

#### Scenario: Warmup

- **WHEN** the server is in its warmup stage
- **THEN** the clock reports phase "warmup", with the warmup time left when warmup has a time limit

#### Scenario: Time limit extended

- **WHEN** the time limit is raised during the match, by overtime or an admin command
- **THEN** the next state reports the time left against the new limit
- **AND** the phase is "overtime" when overtime was added

#### Scenario: Match over

- **WHEN** the match has ended and the scoreboard or map vote is showing
- **THEN** the clock reports phase "ended" and no time left

### Requirement: A paused server's clock is frozen

The clock SHALL report when the server is paused, including when it is autopaused because no human is connected, and SHALL then keep the time it had rather than counting on.

#### Scenario: Autopaused with nobody connected

- **WHEN** the last human leaves and the server pauses itself
- **THEN** the clock reports paused
- **AND** the time left stays at the value it had when the server paused

#### Scenario: Resumed

- **WHEN** a human joins and the server resumes
- **THEN** the clock is no longer reported paused and counts down again

### Requirement: The score limit is reported

The match state SHALL report the live score limit and what it counts for the current gametype (frags, captures, points...), or that there is none.

#### Scenario: Deathmatch with a frag limit

- **WHEN** the gametype is deathmatch and the score limit is 30
- **THEN** the state reports a limit of 30 frags

#### Scenario: No score limit

- **WHEN** the score limit is 0
- **THEN** the state reports no score limit

### Requirement: The scoreboard lists players with the game's score columns

The match state SHALL list every connected player with their raw and plain name, whether they are a bot, ping, time played, team, and a value for each score column the game reports for the current gametype, in the game's column order. It SHALL leave out columns the game marks as internal (Elo and rounds played) and unnamed columns.

#### Scenario: Deathmatch

- **WHEN** a deathmatch is in progress with two humans and a bot
- **THEN** the scoreboard lists three players with columns including score, kills, deaths and suicides
- **AND** the bot is marked as a bot

#### Scenario: Gametype with extra columns

- **WHEN** the gametype reports extra score columns, such as captures in Capture the Flag
- **THEN** those columns are included without the panel needing to know the gametype

#### Scenario: Spectators

- **WHEN** a connected client is spectating
- **THEN** it is listed as a spectator, apart from the players, without scores

### Requirement: The scoreboard is sorted as the game sorts it

Players SHALL be ordered by the game's primary score column, then its secondary column, each from best to worst, where lower values are better for columns the game marks that way. Ties SHALL be broken by name.

#### Scenario: Ordered by score

- **WHEN** one player has score 12 and another 8
- **THEN** the player with 12 is listed first

#### Scenario: Lower is better

- **WHEN** the sort column is one the game marks lower-is-better
- **THEN** the player with the lower value is listed first

### Requirement: Team games show team totals

In a team gametype, the match state SHALL report each team with its colour and its team score columns, and SHALL say which team each player is on.

#### Scenario: Team deathmatch

- **WHEN** a team deathmatch is played by red and blue
- **THEN** the state reports a red and a blue team with their scores
- **AND** each player is reported on their team

#### Scenario: Not a team game

- **WHEN** the gametype has no teams
- **THEN** no teams are reported

### Requirement: Live match state degrades instead of failing

Each part of the match state SHALL be reported as unavailable on its own when the server does not provide it, with the parts that are available still shown.

#### Scenario: Event log unavailable

- **WHEN** the server's event log is not working, so it prints no score dump
- **THEN** the scoreboard is reported unavailable
- **AND** the clock is still reported

#### Scenario: Clock unreadable

- **WHEN** the server does not answer the clock queries
- **THEN** the clock is reported unavailable
- **AND** the scoreboard is still reported

#### Scenario: Server not running

- **WHEN** the server is stopped or starting
- **THEN** the match state says there is no match in progress

#### Scenario: Server does not answer

- **WHEN** a read gets no reply in time
- **THEN** the last state is kept and the panel tries again on the next read

### Requirement: The dashboard shows the match clock and scoreboard

While the server is running a match, the dashboard SHALL show the clock (time left as minutes and seconds, or the phase when there is no time to show), whether the server is paused, the score limit, and the scoreboard with player names in their game colours. These SHALL update live without a reload.

#### Scenario: Match in progress

- **WHEN** the dashboard is open during a match
- **THEN** it shows the time left counting down about once a second
- **AND** the scoreboard with every player's scores in the game's order

#### Scenario: Paused

- **WHEN** the server is paused
- **THEN** the dashboard shows the clock as paused and stopped

#### Scenario: Team game

- **WHEN** a team game is in progress
- **THEN** the scoreboard groups players under their team's totals, in the team's colour

#### Scenario: Part unavailable

- **WHEN** the scoreboard or the clock is unavailable
- **THEN** the dashboard says so in its place and shows the other part

#### Scenario: No match

- **WHEN** the server is stopped
- **THEN** the dashboard shows no clock or scoreboard
