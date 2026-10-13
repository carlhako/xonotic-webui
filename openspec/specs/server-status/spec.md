# server-status Specification

## Purpose

Tells the operator and the web interface what the server is doing right now: its lifecycle state, the match in progress and who is connected, available both as a snapshot and as a live stream, plus a liveness check for tooling.

## Requirements

### Requirement: A status snapshot is available on demand

The panel SHALL provide a current-status snapshot containing the lifecycle state, the current map and gametype when known, the connected players, and the most recent crash information.

#### Scenario: Server running with a match in progress

- **WHEN** status is requested while the server is `running` and a match is in progress
- **THEN** the snapshot reports state `running`
- **AND** it includes the current map and gametype
- **AND** it includes the connected players

#### Scenario: Server stopped

- **WHEN** status is requested while the server is `stopped`
- **THEN** the snapshot reports state `stopped`
- **AND** map and gametype are absent
- **AND** the player list is empty

### Requirement: Status changes are streamed live

The panel SHALL push a status update to every connected client whenever the reported status changes, starting with the current snapshot on connect.

#### Scenario: Client connects

- **WHEN** a client opens the status stream
- **THEN** it immediately receives the current snapshot

#### Scenario: A player joins

- **WHEN** a player joins the server
- **THEN** every connected client receives an updated snapshot showing the player

#### Scenario: State changes

- **WHEN** the lifecycle state changes
- **THEN** every connected client receives an updated snapshot

### Requirement: Connected players are reported with bots distinguished

The snapshot SHALL list each connected player with a display name and whether it is a bot, and SHALL report human and bot counts separately.

#### Scenario: Humans and bots connected

- **WHEN** three humans and two bots are connected
- **THEN** the snapshot lists five players
- **AND** it reports three humans and two bots

#### Scenario: Player leaves

- **WHEN** a player disconnects
- **THEN** that player is no longer listed in the next snapshot

#### Scenario: Name changes

- **WHEN** a connected player changes their name
- **THEN** the next snapshot shows the new name for that player

### Requirement: Map and gametype follow the match

The snapshot SHALL report the map and gametype of the match currently being played and SHALL update them when a new match starts.

#### Scenario: Map change

- **WHEN** the server changes to a new map
- **THEN** the next snapshot reports the new map and its gametype

#### Scenario: Not yet known

- **WHEN** the server is running but no match start has been observed
- **THEN** map and gametype are reported as unknown rather than guessed

### Requirement: Status is not stale after the server stops

When the server stops or exits, the panel SHALL clear the player list, map and gametype from the snapshot.

#### Scenario: Server crashes with players connected

- **WHEN** the server exits unexpectedly while players are connected
- **THEN** the next snapshot lists no players
- **AND** it records the crash

### Requirement: Crash and restart state is visible

The snapshot SHALL report the most recent unexpected exit with its time and status, and whether automatic restart has been abandoned.

#### Scenario: Restart abandoned

- **WHEN** automatic restart was abandoned after repeated crashes
- **THEN** the snapshot says so and includes the last crash

#### Scenario: No crashes

- **WHEN** the server has not crashed since the panel started
- **THEN** no crash information is reported

### Requirement: A liveness check is independent of the game server

The panel SHALL expose a health endpoint that reports the panel's version and answers whether or not the game server is running.

#### Scenario: Server stopped

- **WHEN** the health endpoint is requested while the game server is `stopped`
- **THEN** it responds successfully with the panel version

#### Scenario: Panel not serving

- **WHEN** the panel process is not accepting connections
- **THEN** the health check fails
