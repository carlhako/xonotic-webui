# player-stats Specification

## Purpose

Keeps a lasting history of everyone who plays on the server (who they are, how long and how often they play, and how well) and shows it to the operator as a sortable table of players with a detail view for each.

## Requirements

### Requirement: Player history persists

The panel SHALL keep every player's recorded history across panel restarts, game server restarts, crashes and panel upgrades, and SHALL keep it indefinitely.

#### Scenario: Panel restarted

- **WHEN** players have been recorded and the panel restarts
- **THEN** the players and their totals are listed as before

#### Scenario: Server stopped

- **WHEN** the game server stops
- **THEN** recorded players and their totals remain listed

### Requirement: A player is identified by their key, else by name

The panel SHALL identify a human player by the key fingerprint the server reports for them, so that renames and address changes keep one history. When the server reports no fingerprint for them, it SHALL identify them by their name with colour codes removed.

#### Scenario: Returning player with a new name

- **WHEN** a player whose key was recorded before joins under a different name
- **THEN** their activity is added to the existing player's history

#### Scenario: Two players share a name

- **WHEN** two players with different keys both play as `Player`
- **THEN** they are recorded as two separate players

#### Scenario: No fingerprint available

- **WHEN** the server reports no fingerprint for a joining human
- **THEN** the player is identified by their colour-stripped name
- **AND** a later visit under the same name with no fingerprint is added to that same player

#### Scenario: Name differs only in colour

- **WHEN** a player without a fingerprint plays as `^1Ace` and later as `^4Ace`
- **THEN** both visits are recorded for the same player

### Requirement: Names a player has used are recorded

The panel SHALL record every name a player joins with or changes to, with colour codes intact, and SHALL show the most recently used one as the player's name.

#### Scenario: Rename during play

- **WHEN** a recorded player changes their name in game
- **THEN** the new name becomes the player's shown name
- **AND** the earlier name stays in the list of names used

### Requirement: Time on server is recorded per session

The panel SHALL record each session from a player's join to their departure as time on server, including time spent spectating. A map change SHALL NOT end a session for a player who stays connected.

#### Scenario: Player stays across a map change

- **WHEN** a player is connected through a map change
- **THEN** one session covers their whole visit

#### Scenario: Player leaves

- **WHEN** a player disconnects
- **THEN** their session ends at that moment and its length is added to their time on server

#### Scenario: Server stops with players connected

- **WHEN** the game server stops or exits unexpectedly while players are connected
- **THEN** each of their sessions ends at the moment the server stopped

### Requirement: Kills and deaths are counted as they happen

The panel SHALL count frags, deaths, suicides and team kills from the server's kill events as they occur. A frag counts for the killer and a death for the victim. A suicide or an environmental death counts as a death, and a suicide also counts as a suicide. A team kill counts as a team kill, not a frag.

#### Scenario: Frag

- **WHEN** player A fragged player B
- **THEN** A's frags increase by one
- **AND** B's deaths increase by one

#### Scenario: Suicide

- **WHEN** a player kills themselves
- **THEN** their suicides and deaths each increase by one
- **AND** their frags are unchanged

#### Scenario: Match never finishes

- **WHEN** frags occurred in a match that ends in a server crash
- **THEN** those frags and deaths remain counted

### Requirement: End-of-match statistics are recorded

At the end of every match, the panel SHALL record from the server's statistics report each player's score, time playing, damage dealt and taken, per-weapon shots, hits and frags, achievements, average ping, and win.

#### Scenario: Match ends normally

- **WHEN** a match reaches its limit with players in it
- **THEN** each participant's score, time playing, damage, weapon statistics and achievements are recorded for that match
- **AND** the winner is recorded as having won it

#### Scenario: Player left before the end

- **WHEN** a player took part in a match and left before it ended
- **THEN** their statistics for that match are still recorded for them

#### Scenario: Match cut short

- **WHEN** a match is ended early by a map change or the server stopping cleanly
- **THEN** its statistics are recorded
- **AND** it does not count as a finished match or a win for anyone

#### Scenario: Server crashes mid-match

- **WHEN** the game server exits unexpectedly during a match
- **THEN** that match has no end-of-match statistics
- **AND** nothing already recorded is lost

### Requirement: Statistics capture cannot be redirected

The panel SHALL configure the server to deliver its statistics report to the panel at every start, and SHALL NOT let settings change this. As a result the server SHALL NOT submit match statistics to any external statistics service.

#### Scenario: Server starts

- **WHEN** the game server starts
- **THEN** its end-of-match statistics report is delivered to the panel
- **AND** it is not submitted to an external statistics service

### Requirement: Bots are recorded and marked

The panel SHALL record bots as players, marked as bots, so that frags against them and their own activity are kept. Bots SHALL be identified by name.

#### Scenario: Bot in a match

- **WHEN** a bot plays a match
- **THEN** it is recorded as a player marked as a bot

#### Scenario: Frag against a bot

- **WHEN** a human frags a bot
- **THEN** the frag counts for the human

### Requirement: Recording is limited to what is needed

The panel SHALL NOT store players' IP addresses. It SHALL show a player's key fingerprint only as a short prefix.

#### Scenario: Player joins

- **WHEN** a human player joins
- **THEN** no IP address of theirs is stored

#### Scenario: Fingerprint displayed

- **WHEN** a player's details are shown
- **THEN** at most the first eight characters of their key fingerprint are shown

### Requirement: Recording problems do not disturb the server

A failure to record or store player statistics SHALL NOT stop, restart or delay the game server, and SHALL NOT affect other panel features. The failure SHALL be logged.

#### Scenario: Storage unavailable

- **WHEN** the player history cannot be written
- **THEN** the game server and the rest of the panel keep working
- **AND** the failure is logged

#### Scenario: Fingerprint lookup gets no answer

- **WHEN** the server does not answer a fingerprint lookup in time
- **THEN** the player is identified by name for that visit

### Requirement: Player totals are available from the API

The panel SHALL provide a list of recorded players with their totals: frags, deaths, kill/death ratio, suicides, score, wins, finished matches, time playing, time on server, accuracy, first seen and last seen. It SHALL also provide one player's full details.

#### Scenario: List players

- **WHEN** the player list is requested
- **THEN** every recorded player is returned with their totals and whether they are a bot

#### Scenario: Player with no deaths

- **WHEN** a player has frags and no deaths
- **THEN** their kill/death ratio is reported as equal to their frag count, not as an error or infinity

#### Scenario: Unknown player

- **WHEN** details are requested for a player that does not exist
- **THEN** a not-found error is returned

### Requirement: The Players section lists players in a sortable table

The interface SHALL list a Players section in the navigation. It SHALL show recorded players in a table whose columns are name, frags, deaths, K/D, score, wins, matches, time playing, time on server, accuracy and last seen, sorted by frags (highest first) by default.

#### Scenario: Sort by a column

- **WHEN** the operator activates a column heading
- **THEN** the table is sorted by that column
- **AND** activating the same heading again reverses the order

#### Scenario: Names in colour

- **WHEN** a player's name contains colour codes
- **THEN** it is shown in its colours without raw code characters

#### Scenario: Nobody recorded yet

- **WHEN** no players have been recorded
- **THEN** the section says so instead of showing an empty table

#### Scenario: Reload the section

- **WHEN** a browser requests the Players section's route directly
- **THEN** the web interface loads and shows the Players section

### Requirement: Large player lists are paged

The Players section SHALL show the sorted, filtered players a page at a time, with the total count and controls to move between pages. Sorting and filtering SHALL apply across all players, not just the page shown.

#### Scenario: Many players

- **WHEN** more players are recorded than fit on one page
- **THEN** the first page of the sorted list is shown with the total number of players
- **AND** the operator can move to the next page

#### Scenario: Sort covers every page

- **WHEN** the operator sorts by time playing
- **THEN** the first page shows the players with the most time playing across all recorded players

### Requirement: The player table can be filtered

The Players section SHALL filter the table by a name search, matching any name a player has used, ignoring colour codes and letter case. Bots SHALL be hidden unless the operator chooses to show them.

#### Scenario: Search by name

- **WHEN** the operator types `ace` in the search
- **THEN** only players who have used a name containing "ace" in any case are listed

#### Scenario: Bots hidden by default

- **WHEN** the Players section opens
- **THEN** bots are not listed
- **AND** turning on "show bots" lists them, marked as bots

### Requirement: The player table stays current

While the Players section is open, the table SHALL refresh on its own so that new players and changed totals appear without a page reload, keeping the operator's sort, search and bot choice.

#### Scenario: Frag while viewing

- **WHEN** a player scores a frag while the operator views the table
- **THEN** that player's frags update within a few seconds without a reload
- **AND** the chosen sort order is kept

### Requirement: A player's details are shown in a dialog

Activating a player in the table SHALL open a dialog with that player's full details: name and names used, short key, first and last seen, sessions, all totals, damage dealt and taken, average ping, a per-weapon table of frags and accuracy, and achievements. It SHALL be dismissible and keyboard accessible.

#### Scenario: Open details

- **WHEN** the operator activates a player's row
- **THEN** a dialog shows that player's details and per-weapon statistics

#### Scenario: Close details

- **WHEN** the operator presses Escape or the close control
- **THEN** the dialog closes and the table is shown as it was

#### Scenario: Player without match statistics

- **WHEN** a player has sessions but has never been in an end-of-match report
- **THEN** the dialog shows their time on server and live counts, and states that no match statistics are recorded yet

### Requirement: The Players section is usable on a phone

The Players section and its detail dialog SHALL be usable at a phone viewport width without horizontal page scrolling. The table MAY scroll sideways within its own area.

#### Scenario: Phone width

- **WHEN** the Players section is viewed at a 375px-wide viewport
- **THEN** the page does not scroll sideways
- **AND** the player dialog fits within the viewport

### Requirement: Maps accumulate play totals from the match history

The panel SHALL total, for every map, the matches played on it, the frags scored on it and when it was last played, from the recorded match history. A match SHALL count as played when it ran to its limit and had at least one recorded participant. Frags SHALL include every frag recorded on the map, whether or not the match finished and whoever scored it, bots included.

#### Scenario: Finished match

- **WHEN** a match on `boil` runs to its limit with players in it
- **THEN** the played total of `boil` increases by one
- **AND** the frags scored in it are added to the frag total of `boil`

#### Scenario: Match cut short

- **WHEN** a match on `boil` is ended early by a map change
- **THEN** it does not add to the played total of `boil`
- **AND** its frags are still added to the frag total of `boil`
- **AND** it counts as the last time `boil` was played

#### Scenario: Bots

- **WHEN** a bot frags a human or another bot on `boil`
- **THEN** that frag is part of the frag total of `boil`

#### Scenario: Match with nobody in it

- **WHEN** a match runs to its limit with no recorded participant
- **THEN** it does not add to the played total of its map

#### Scenario: Map never played

- **WHEN** a map has no recorded matches
- **THEN** its played and frag totals are zero
- **AND** it has no last-played time

#### Scenario: Totals survive restarts

- **WHEN** the panel restarts
- **THEN** every map's totals are the same as before the restart

### Requirement: A map's play details are available from the API

The panel SHALL provide one installed map's details: matches played, matches cut short, total frags, first and last played, matches played per gametype, and the ten players with the most frags on that map, each with their name, frags and whether they are a bot. Players with equal frags SHALL be ordered by name.

#### Scenario: Details of a played map

- **WHEN** the details of `boil` are requested
- **THEN** its played and cut-short counts, frag total, first and last played, per-gametype counts and top fraggers are returned
- **AND** the top fraggers are ordered by frags on `boil`, highest first

#### Scenario: Bot among the top fraggers

- **WHEN** a bot is among the ten players with the most frags on the map
- **THEN** it is listed and marked as a bot

#### Scenario: Gametype not recorded

- **WHEN** a counted match has no recorded gametype
- **THEN** it is grouped under an unknown gametype

#### Scenario: Map never played

- **WHEN** the details of an installed map with no recorded matches are requested
- **THEN** zero counts and empty lists are returned, not an error

#### Scenario: Unknown map

- **WHEN** the details of a map that is not installed are requested
- **THEN** a not-found error is returned

#### Scenario: History not recorded

- **WHEN** player history is not being recorded and a map's details are requested
- **THEN** an error states that player history is unavailable
