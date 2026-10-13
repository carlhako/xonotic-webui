# Spec Delta

## Purpose

Defines the browser application frame that hosts every panel section: how it is served, how the operator navigates it, the dashboard with server controls, and how it behaves when its connection to the panel is lost.

## ADDED Requirements

### Requirement: The interface is served by the panel itself

The panel SHALL serve the web interface from its own port with no separate web server, and SHALL serve the application for any in-app route so that a reload or a bookmarked link works.

#### Scenario: Open the root

- **WHEN** a browser requests the panel's root URL
- **THEN** the web interface loads

#### Scenario: Reload a deep link

- **WHEN** a browser requests an in-app route directly, such as the console page
- **THEN** the web interface loads and shows that section

#### Scenario: API paths are not shadowed

- **WHEN** a request is made to an API path that does not exist
- **THEN** it receives an error response, not the application page

### Requirement: Sections are navigable from a persistent header

The interface SHALL show a persistent header naming the application and listing every section, highlight the current one, and keep the header visible when sections change.

#### Scenario: Switch section

- **WHEN** the operator selects another section
- **THEN** that section is shown without a full page reload
- **AND** the selected section is highlighted

#### Scenario: Initial sections

- **WHEN** the interface loads
- **THEN** the sections Dashboard and Console are listed

### Requirement: The dashboard shows live state and lifecycle controls

The dashboard SHALL show the server's lifecycle state, map, gametype and connected players as they change, and SHALL offer start, stop and restart controls enabled only when valid for the current state.

#### Scenario: Server stopped

- **WHEN** the server is `stopped`
- **THEN** the start control is enabled
- **AND** the stop and restart controls are not

#### Scenario: Server running

- **WHEN** the server is `running`
- **THEN** stop and restart are enabled and start is not

#### Scenario: Transition in progress

- **WHEN** the server is `starting` or `stopping`
- **THEN** all lifecycle controls are disabled
- **AND** the transition is shown as in progress

#### Scenario: Operation fails

- **WHEN** a lifecycle request is rejected or fails
- **THEN** the dashboard shows the error returned

### Requirement: Disruptive actions are confirmed when players are connected

The interface SHALL ask for confirmation before stopping or restarting the server while human players are connected, and SHALL state how many.

#### Scenario: Stop with players

- **WHEN** the operator chooses stop while three humans are connected
- **THEN** a confirmation states that three players will be disconnected
- **AND** the stop proceeds only on confirmation

#### Scenario: Stop with nobody connected

- **WHEN** the operator chooses stop with no humans connected
- **THEN** the stop proceeds without a confirmation

### Requirement: Connection loss is shown and recovered from

When the interface loses its live connection to the panel, it SHALL show a clear banner, SHALL keep trying to reconnect, and SHALL refresh its state and clear the banner on reconnect.

#### Scenario: Panel restarts

- **WHEN** the panel becomes unreachable and then returns
- **THEN** the banner appears while it is unreachable
- **AND** it disappears once reconnected
- **AND** displayed state is replaced with fresh state

#### Scenario: Stale data is not presented as current

- **WHEN** the connection is lost
- **THEN** controls that change the server are disabled until reconnection

### Requirement: Times are shown in the browser's timezone

The interface SHALL display all timestamps in the viewing browser's local timezone and SHALL NOT depend on a timezone configured on the server.

#### Scenario: Timestamp display

- **WHEN** a timestamp is shown
- **THEN** it is formatted in the browser's local timezone

### Requirement: The interface is usable on a phone

The interface SHALL lay out without horizontal page scrolling at a phone viewport width, with controls reachable and legible.

#### Scenario: Phone width

- **WHEN** the interface is viewed at a 375px-wide viewport
- **THEN** the header, dashboard and console are usable without sideways scrolling
