# Spec Delta

## Purpose

Lets the operator control what is played: browse the installed maps, choose the gametype and map rotation, and go to a specific map, skip the current map or restart the match from the panel, including on an empty, idle server.

## ADDED Requirements

### Requirement: Installed maps are listed with their details

The panel SHALL list every playable map installed in the game and in the user data directory, with its title, the gametypes it supports and a preview image when one exists. The list SHALL be available while the server is stopped. Hidden and internal maps SHALL NOT be listed.

#### Scenario: Stock maps

- **WHEN** the operator opens the map list on a fresh install
- **THEN** the stock maps are listed, each with its title, supported gametypes and preview image
- **AND** internal maps such as `_hudsetup` are not listed

#### Scenario: Map added by the operator

- **WHEN** the operator places a map package in the user data directory and opens the map list
- **THEN** that map is listed

#### Scenario: Map with no metadata

- **WHEN** an installed map has no map information file
- **THEN** it is listed with unknown gametypes
- **AND** it is not offered for any gametype

#### Scenario: Server stopped

- **WHEN** the map list is requested while the server is stopped
- **THEN** the list is returned in full

### Requirement: The gametype is selectable and persists

The panel SHALL offer the gametypes supported by at least one installed map and SHALL persist the selected gametype so the server uses it at every start. Changing the gametype SHALL either take effect at the next map or, if the operator also picks a map, immediately via going to that map.

#### Scenario: Only playable gametypes offered

- **WHEN** the operator opens the gametype selector
- **THEN** only gametypes that at least one installed map supports are offered

#### Scenario: Change at next map

- **WHEN** the operator selects Team Deathmatch while a Deathmatch match is in progress
- **THEN** the current match continues
- **AND** the next map is played as Team Deathmatch
- **AND** the change is reported as taking effect at the next map

#### Scenario: Change now

- **WHEN** the operator selects Capture the Flag and chooses to switch now to a map supporting it
- **THEN** the server goes to that map as Capture the Flag

#### Scenario: Persists across restarts

- **WHEN** the gametype is set to Team Deathmatch and the server restarts
- **THEN** the first match after the restart is Team Deathmatch

### Requirement: The map rotation is configurable

The panel SHALL let the operator set an ordered list of maps to rotate through and whether the order is shuffled, and SHALL persist both. An empty list SHALL mean all maps that support the gametype. Maps in the list that do not support the selected gametype SHALL be flagged and left out of the rotation.

#### Scenario: Fixed order

- **WHEN** the rotation is `stormkeep, boil, warfare` with shuffle off and a match ends without a vote
- **THEN** the maps are played in that order

#### Scenario: Default rotation

- **WHEN** the rotation list is empty
- **THEN** the server rotates through all maps that support the gametype

#### Scenario: Incompatible map in the list

- **WHEN** the rotation contains `catharsis` and the gametype is Team Deathmatch
- **THEN** `catharsis` is shown as not supporting the gametype
- **AND** it is not played while the gametype is Team Deathmatch

#### Scenario: Rotation shown as configured

- **WHEN** the operator views the rotation while the server is running
- **THEN** the list is shown as the operator saved it, not as the server has reordered it

### Requirement: The operator can go to a specific map

The panel SHALL let the operator change to a chosen map that supports the current gametype. With players connected, the match SHALL end with the scoreboard and then change to that map without a vote. A map that is not installed or does not support the gametype SHALL be rejected with an error saying which.

#### Scenario: Players connected

- **WHEN** the operator goes to `warfare` while players are connected
- **THEN** the current match ends with the scoreboard
- **AND** the next match is on `warfare` with no map vote

#### Scenario: Unsupported map

- **WHEN** the operator goes to `catharsis` while the gametype is Team Deathmatch
- **THEN** the request is rejected with an error stating that `catharsis` does not support Team Deathmatch
- **AND** the current match continues

#### Scenario: Unknown map

- **WHEN** the operator goes to a map that is not installed
- **THEN** the request is rejected with an error stating the map is not installed

### Requirement: The operator can skip the current map

The panel SHALL let the operator end the current match early. The server SHALL then move on as at a normal match end: the scoreboard, then the map vote when voting is enabled and players are connected, otherwise the next map in the rotation.

#### Scenario: Skip with players

- **WHEN** the operator skips while players are connected and map voting is enabled
- **THEN** the match ends with the scoreboard and the map vote
- **AND** the voted map is played next

#### Scenario: Skip with nobody connected

- **WHEN** the operator skips while no players are connected
- **THEN** the next map in the rotation starts

### Requirement: The operator can restart the current match

The panel SHALL let the operator restart the current match on the same map, resetting scores.

#### Scenario: Restart

- **WHEN** the operator restarts the match on `boil`
- **THEN** a new match starts on `boil`

### Requirement: Map actions work on an idle, auto-paused server

Go to map, skip and restart SHALL complete when no players are connected, including when the server has paused itself because it is empty, and SHALL leave idle auto-pause enabled. The panel SHALL NOT pause or unpause a server that has players connected.

#### Scenario: Skip on a paused empty server

- **WHEN** the server has been empty long enough to auto-pause and the operator skips
- **THEN** the next map starts within a few seconds
- **AND** the server pauses itself again once the new map has been idle

#### Scenario: Go to map on a paused empty server

- **WHEN** the server is empty and auto-paused and the operator goes to `warfare`
- **THEN** the next match is on `warfare` within a few seconds

#### Scenario: Empty but not paused

- **WHEN** a player joined and left so the empty server is still running, and the operator skips
- **THEN** the next map starts
- **AND** the server is not left paused in the middle of the old match

#### Scenario: Players connected

- **WHEN** players are connected and the operator skips
- **THEN** players see no pause or unpause messages

#### Scenario: Pause handling stays out of the console

- **WHEN** the panel unpauses the server to carry out an action
- **THEN** the pause commands and their replies do not appear in the console stream

### Requirement: The outcome of a map action is shown

The panel SHALL show every connected client that a map action is pending, and then whether it succeeded, judged by the next match actually starting, or did not complete within a time limit that allows for the scoreboard and a full map vote.

#### Scenario: Success

- **WHEN** the operator goes to `warfare` and the next match starts on `warfare`
- **THEN** every client sees the action as completed

#### Scenario: No match start

- **WHEN** an action is sent but no new match starts within the time limit
- **THEN** every client sees the action as not completed

#### Scenario: Pending visible to others

- **WHEN** one operator skips the map
- **THEN** another open browser shows the skip as pending until the next match starts

### Requirement: Map actions are exclusive and need a running server

Only one map action SHALL be pending at a time; another SHALL be rejected while one is pending. Map actions SHALL be rejected when the server is not running.

#### Scenario: Second action while pending

- **WHEN** a skip is pending and the operator requests go to map
- **THEN** the second request is rejected with an error stating an action is in progress

#### Scenario: Server stopped

- **WHEN** the operator skips while the server is stopped
- **THEN** the request is rejected with an error stating the server is not running

### Requirement: Disruptive map actions are confirmed when players are connected

The interface SHALL ask for confirmation before going to a map, skipping or restarting the match while human players are connected, and SHALL state how many. With no humans connected it SHALL proceed without confirmation.

#### Scenario: Skip with players

- **WHEN** the operator chooses skip while two humans are connected
- **THEN** a confirmation states that two players are in the match
- **AND** the skip proceeds only on confirmation

#### Scenario: Skip with nobody connected

- **WHEN** the operator chooses skip with no humans connected
- **THEN** the skip proceeds without confirmation
