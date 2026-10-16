# Spec Delta

## Purpose

Keeps a browsable record of every match played on the server, each with its map, gametype,
outcome and final scoreboard, so the operator can look back at past games.

## ADDED Requirements

### Requirement: Matches with a human are listed

The panel SHALL list every recorded match in which at least one human took part, newest
first. A match where only bots took part, or nobody, SHALL NOT be listed. A human counts as
having taken part when they have a recorded frag, death, suicide or team kill in the match,
or appear in its end-of-match report.

#### Scenario: Human in the match

- **WHEN** a human plays a match on `boil` with two bots
- **THEN** that match is listed

#### Scenario: Bots only

- **WHEN** a match is recorded in which only bots took part
- **THEN** it is not listed

#### Scenario: Newest first

- **WHEN** matches were played at 20:00 and 21:00
- **THEN** the 21:00 match is listed before the 20:00 match

#### Scenario: Recorded before this change

- **WHEN** matches were recorded by an earlier panel version
- **THEN** they are listed as well

### Requirement: Each listed match shows its summary

Each listed match SHALL show its start time, map, gametype, duration when known, outcome,
the number of humans and of bots who took part, and its winner when it has one. The winner
SHALL be the winning team in a team game and the winning player otherwise.

#### Scenario: Deathmatch won by a player

- **WHEN** a deathmatch ran to its limit and `^1Ace` won it
- **THEN** its summary names `^1Ace` as the winner

#### Scenario: Team game

- **WHEN** a team deathmatch ran to its limit and red won
- **THEN** its summary names the red team as the winner

#### Scenario: No winner

- **WHEN** a match was cut short or has no report
- **THEN** its summary has no winner

#### Scenario: Gametype not recorded

- **WHEN** a match has no recorded gametype
- **THEN** its gametype is shown as unknown

### Requirement: A match's outcome is reported

Each match SHALL have one outcome: **finished** when it ran to its limit, **cut short**
when it was ended early by a map change, vote or clean server stop, **in progress** while
it is the match being played, or **no report** when it ended without an end-of-match report,
such as in a crash.

#### Scenario: Ran to its limit

- **WHEN** a match reaches its frag limit
- **THEN** its outcome is finished

#### Scenario: Map changed by the operator

- **WHEN** the operator changes map mid-match
- **THEN** that match's outcome is cut short

#### Scenario: Being played

- **WHEN** the server is running a match that already has a recorded frag
- **THEN** that match is listed with the outcome in progress

#### Scenario: Server crashed

- **WHEN** the game server exits unexpectedly during a match
- **THEN** that match's outcome is no report

### Requirement: Matches against bots are tagged

A match SHALL be tagged **vs bots** when exactly one human and at least one bot took part in
it. The tag SHALL be worked out from the recorded participants, so matches recorded before
this feature are tagged too.

#### Scenario: One human and bots

- **WHEN** one human plays a match against three bots
- **THEN** the match is tagged vs bots

#### Scenario: Two humans

- **WHEN** two humans and a bot take part in a match
- **THEN** the match is not tagged vs bots

#### Scenario: One human alone

- **WHEN** one human takes part in a match with no bots
- **THEN** the match is not tagged vs bots

### Requirement: The match list can be filtered and is paged

The match list SHALL be filterable by map, by gametype, by one player who took part, and by
whether to leave out vs-bots matches. The filters SHALL combine. The list SHALL be paged,
with the total number of matching matches.

#### Scenario: Filter by map and gametype

- **WHEN** the list is filtered to map `boil` and gametype `ctf`
- **THEN** only CTF matches on `boil` are returned

#### Scenario: Hide vs bots

- **WHEN** vs-bots matches are left out
- **THEN** no match tagged vs bots is returned

#### Scenario: One player's matches

- **WHEN** the list is filtered to a player
- **THEN** only matches that player took part in are returned, including ones they left early

#### Scenario: Many matches

- **WHEN** more matches match than fit on one page
- **THEN** the first page is returned with the total count

### Requirement: The final scoreboard of each match is kept

For every match from this version on, the panel SHALL keep, from its end-of-match report,
each player's team, final board position, every scoreboard value the game reports, and the
name they used in that match, plus each team's scores. It SHALL keep them for as long as
the match is kept.

#### Scenario: Team game ends

- **WHEN** a team deathmatch ends with a report
- **THEN** each player's team and scoreboard values and each team's score are kept

#### Scenario: Gametype with extra columns

- **WHEN** a CTF match ends with a report that includes captures and returns
- **THEN** those values are kept for each player without the panel needing to know CTF

#### Scenario: Player renamed later

- **WHEN** a player played as `^1Ace` and later renamed to `^4Ace`
- **THEN** that match still shows them as `^1Ace`

#### Scenario: Panel restarted

- **WHEN** the panel restarts
- **THEN** every kept scoreboard is shown as before

### Requirement: A match's details are available from the API

The panel SHALL provide one match's details: its summary and its final scoreboard. The
scoreboard SHALL list every player who took part, in the game's board order. Each player
SHALL have their name, whether they are a bot, team, scoreboard values, average ping, time
playing, and whether they were playing when it ended.

#### Scenario: Finished deathmatch

- **WHEN** the details of a finished deathmatch are requested
- **THEN** its players are returned in the game's final board order with their scores

#### Scenario: Player left early

- **WHEN** a player took part in a match and left before it ended
- **THEN** they are in the scoreboard, after the players who stayed, marked as not playing at the end

#### Scenario: Team game

- **WHEN** the details of a finished team game are requested
- **THEN** each team is returned with its colour and scores, and each player with their team

#### Scenario: Match without a report

- **WHEN** the details of a match with no end-of-match report are requested
- **THEN** each player's recorded frags, deaths, suicides and team kills are returned as their values

#### Scenario: Unknown match

- **WHEN** the details of a match that does not exist are requested
- **THEN** a not-found error is returned

#### Scenario: History not recorded

- **WHEN** player history is not being recorded
- **THEN** match list and details requests return an error stating that player history is unavailable

### Requirement: Matches recorded before this version show what was kept

Matches recorded before the panel kept full scoreboards SHALL show the figures that were
recorded for them, without team grouping or team scores, under each player's current name.

#### Scenario: Old team match

- **WHEN** a team deathmatch recorded by an earlier version is opened
- **THEN** its players are listed with their recorded scores, without team grouping
- **AND** no error is shown

### Requirement: The Matches section lists past matches

The interface SHALL list a Matches section in the navigation. It SHALL show the match list
as a table of start time, map, gametype, duration, outcome, players, winner and the vs-bots
tag, a page at a time, with controls for the map, gametype and hide-vs-bots filters.

#### Scenario: Open the section

- **WHEN** the operator opens the Matches section
- **THEN** the most recent matches are shown, newest first

#### Scenario: Nothing recorded yet

- **WHEN** no match is listed
- **THEN** the section says so instead of showing an empty table

#### Scenario: Reload the section

- **WHEN** a browser requests the Matches section's route directly
- **THEN** the web interface loads and shows the Matches section

#### Scenario: History unavailable

- **WHEN** player history is not being recorded
- **THEN** the section says that player history is not being recorded

### Requirement: The match list stays current

While the Matches section is open, the list SHALL refresh on its own so a match that ends or
starts appears without a reload, keeping the operator's filters and page.

#### Scenario: Match ends while viewing

- **WHEN** a match ends while the operator views the first page
- **THEN** its outcome updates within a few seconds without a reload

### Requirement: A match's details are shown in a dialog

Activating a match in the list SHALL open a dialog with its summary and final scoreboard,
showing names in their game colours, bots marked, team games grouped under their team's
totals in the team's colour, and players who were not playing at the end marked. It SHALL be dismissible
and keyboard accessible.

#### Scenario: Open details

- **WHEN** the operator activates a match's row
- **THEN** a dialog shows that match's scoreboard

#### Scenario: Close details

- **WHEN** the operator presses Escape or the close control
- **THEN** the dialog closes and the list is shown as it was

#### Scenario: Open a player

- **WHEN** the operator activates a player in the match's scoreboard
- **THEN** that player's details dialog opens
