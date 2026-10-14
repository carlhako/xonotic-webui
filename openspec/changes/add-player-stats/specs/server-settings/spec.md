# Spec Delta

## MODIFIED Requirements

### Requirement: The panel's own dependencies cannot be overridden

The panel SHALL refuse to set, through any setting or raw override, the cvars it forces for its own operation (the event log, console colour and statistics report settings) and the game port. It SHALL also refuse to set `rcon_password`.

#### Scenario: Event log override refused

- **WHEN** the operator tries to add a raw override `sv_eventlog 0`
- **THEN** the request is rejected with an error naming the cvar as reserved
- **AND** nothing is saved

#### Scenario: Statistics report override refused

- **WHEN** the operator tries to add a raw override for `g_playerstats_gamereport_uri`
- **THEN** the request is rejected with an error naming the cvar as reserved
- **AND** nothing is saved

#### Scenario: rcon password refused

- **WHEN** the operator tries to add a raw override for `rcon_password`
- **THEN** the request is rejected and nothing is saved

### Requirement: Curated settings cover common server options

The panel SHALL offer typed, validated settings with labels and help text for: hostname, message of the day, maximum players, public server listing, time/score/lead limits, warmup, bot count, minimum players, bot skill, map voting, common mutators and idle auto-pause. Each SHALL show its current value and default.

#### Scenario: Viewing settings

- **WHEN** the operator opens the settings
- **THEN** each curated setting shows its saved value or that it uses the default
- **AND** when the server is running, the value currently in effect on the server

#### Scenario: Out-of-range value

- **WHEN** the operator enters a bot skill of 99
- **THEN** the save is rejected with an error stating the allowed range
- **AND** nothing is saved

#### Scenario: Auto-pause on by default

- **WHEN** the operator has never changed the idle auto-pause setting
- **THEN** it is reported as enabled

#### Scenario: No statistics reporting setting

- **WHEN** the operator opens the settings
- **THEN** there is no setting for uploading match statistics, because the panel forces where the report goes
