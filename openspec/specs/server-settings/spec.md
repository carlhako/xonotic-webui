# server-settings Specification

## Purpose

Lets the operator view and change the Xonotic server's settings from the panel: settings persist independently of the hand-edited `server.cfg`, are applied live where the game allows, and the operator is told when each change takes effect.

## Requirements

### Requirement: Settings persist and are applied at every start

The panel SHALL store the operator's settings itself and apply them every time the server starts, without modifying `server.cfg`. Settings SHALL be readable and writable whether or not the server is running.

#### Scenario: Setting survives a restart

- **WHEN** the operator sets the hostname to "LAN Party" and the server is later restarted
- **THEN** the restarted server uses the hostname "LAN Party"

#### Scenario: Setting changed while stopped

- **WHEN** the operator changes a setting while the server is stopped
- **THEN** the change is saved
- **AND** it is in effect once the server next starts

#### Scenario: server.cfg untouched

- **WHEN** the operator saves any setting
- **THEN** the contents of `server.cfg` are unchanged

#### Scenario: Survives a panel restart

- **WHEN** the panel itself restarts
- **THEN** the previously saved settings are still reported and still applied

#### Scenario: Fresh install

- **WHEN** no setting has ever been saved
- **THEN** the server behaves exactly as its `server.cfg` configures it

### Requirement: Panel settings take precedence over server.cfg

When a setting is configured both by the panel and in `server.cfg`, the panel's value SHALL be the one in effect. The panel SHALL show which of its settings are also set in `server.cfg`, as far as simple top-level assignments there reveal.

#### Scenario: Both set a value

- **WHEN** `server.cfg` sets `timelimit_override 20` and the panel's time limit is 10
- **THEN** the server uses a time limit of 10

#### Scenario: Overlap is shown

- **WHEN** `server.cfg` contains `hostname "Old Name"` and the operator views the settings
- **THEN** the hostname setting is marked as also set in `server.cfg`, with the panel's value taking precedence

### Requirement: The panel's own dependencies cannot be overridden

The panel SHALL refuse to set, through any setting or raw override, the cvars it forces for its own operation (the event log and console colour settings) and the game port. It SHALL also refuse to set `rcon_password`.

#### Scenario: Event log override refused

- **WHEN** the operator tries to add a raw override `sv_eventlog 0`
- **THEN** the request is rejected with an error naming the cvar as reserved
- **AND** nothing is saved

#### Scenario: rcon password refused

- **WHEN** the operator tries to add a raw override for `rcon_password`
- **THEN** the request is rejected and nothing is saved

### Requirement: Saving reports when each change takes effect

When a setting is saved, the panel SHALL report for each changed setting whether it took effect immediately, takes effect at the next map, or takes effect when the server next starts.

#### Scenario: Immediate setting

- **WHEN** the operator changes the hostname while the server is running
- **THEN** the change is applied to the running server
- **AND** it is reported as taking effect now

#### Scenario: Next-map setting

- **WHEN** the operator enables the instagib mutator while the server is running
- **THEN** it is reported as taking effect at the next map
- **AND** the next map starts with instagib enabled

#### Scenario: Next-start setting

- **WHEN** the operator changes the maximum player count while the server is running
- **THEN** it is reported as taking effect when the server restarts
- **AND** the operator is offered a restart

#### Scenario: Saved while stopped

- **WHEN** a setting is saved while the server is stopped
- **THEN** it is reported as taking effect when the server starts

### Requirement: Curated settings cover common server options

The panel SHALL offer typed, validated settings with labels and help text for: hostname, message of the day, maximum players, public server listing, time/score/lead limits, warmup, bot count, minimum players, bot skill, map voting, common mutators, idle auto-pause and match statistics reporting. Each SHALL show its current value and default.

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

### Requirement: Match limits persist across map changes

Time, score and lead limits set in the panel SHALL apply to every map, not only to the match in progress. A limit can be set to "map default" to use each map's own limit, or to 0 for no limit. When the server is running, a changed limit SHALL also apply to the current match.

#### Scenario: Limit survives a map change

- **WHEN** the operator sets the time limit to 10 minutes and the map changes
- **THEN** the new match also has a 10 minute time limit

#### Scenario: Applies to the current match

- **WHEN** the operator sets the score limit to 50 during a match
- **THEN** the current match's score limit becomes 50
- **AND** the change is reported as taking effect now

#### Scenario: Back to map default

- **WHEN** the operator sets the time limit back to "map default" during a match
- **THEN** it is reported as taking effect at the next map
- **AND** the next map uses its own default time limit

#### Scenario: Unit follows the gametype

- **WHEN** the selected gametype is Capture the Flag
- **THEN** the score limit is described in captures rather than frags

### Requirement: Any cvar can be overridden

The panel SHALL let the operator add, change and remove a raw override for any cvar not reserved by the panel, including cvars the panel does not know. A raw override SHALL be reported as possibly needing a map change or restart to take effect.

#### Scenario: Add an override

- **WHEN** the operator adds the override `g_balance_health_start` = `150`
- **THEN** it is saved, applied at every start, and sent to the server if it is running
- **AND** it is reported as possibly needing a map change or restart

#### Scenario: Remove an override

- **WHEN** the operator removes a raw override
- **THEN** it is no longer applied when the server next starts

#### Scenario: Invalid name

- **WHEN** the operator adds an override whose name contains a space or a semicolon
- **THEN** it is rejected and nothing is saved

### Requirement: Setting values cannot inject console commands

The panel SHALL accept only single-line values without control characters, double quotes or backslashes, and SHALL deliver every value so that it is taken literally. Characters that the game console treats specially, such as `;` and `$`, SHALL reach the server unchanged.

#### Scenario: Semicolon in a value

- **WHEN** the operator sets the message of the day to `Welcome; have fun`
- **THEN** the server's message of the day is exactly `Welcome; have fun`
- **AND** no other console command is run

#### Scenario: Dollar sign in a value

- **WHEN** the operator sets the hostname to `$hostname rocks`
- **THEN** the server's hostname is exactly `$hostname rocks`

#### Scenario: Rejected characters

- **WHEN** the operator enters a value containing a newline, a double quote or a backslash
- **THEN** the save is rejected with an error naming the disallowed character

#### Scenario: Colour codes allowed

- **WHEN** the operator sets the hostname to `^1Red ^xF80Server`
- **THEN** it is accepted and used as entered

### Requirement: The cvar catalogue is searchable

The panel SHALL let the operator search all of the game's cvars by name or description, showing each one's default and description at any time. When the server is running it SHALL also show the current value. Searching SHALL NOT flood or evict the console history.

#### Scenario: Search while stopped

- **WHEN** the operator searches for "maplist" while the server is stopped
- **THEN** matching cvars are listed with their defaults and descriptions

#### Scenario: Search while running

- **WHEN** the operator searches for "maplist" while the server is running
- **THEN** the listed cvars also show their current values

#### Scenario: Console history preserved

- **WHEN** the operator browses the catalogue while the server is running
- **THEN** the console history seen by clients is unchanged by those lookups

#### Scenario: Reserved cvar shown read-only

- **WHEN** a search result is a cvar the panel reserves
- **THEN** it is shown but cannot be overridden

### Requirement: Changes made by the panel are visible in the console

Each setting the panel applies to the running server SHALL appear in the console history as a command, as an operator command would.

#### Scenario: Live change visible

- **WHEN** the operator changes the bot count while the server is running
- **THEN** the corresponding command appears in the console stream
