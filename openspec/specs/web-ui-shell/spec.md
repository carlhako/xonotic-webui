# web-ui-shell Specification

## Purpose

Defines the browser application frame that hosts every panel section: how it is served, how the operator navigates it, the dashboard with server controls, and how it behaves when its connection to the panel is lost.

## Requirements

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

### Requirement: The interface is laid out for a desktop browser

The interface SHALL be designed for a desktop browser. Page content SHALL use up to 1280px of width on every section, centred in wider windows. Small screens such as phones are not supported.

#### Scenario: Wide window

- **WHEN** any section is viewed in a browser window wider than 1280px
- **THEN** its content is 1280px wide and centred

#### Scenario: Maps file table fits

- **WHEN** the Maps section's file view is shown in a 1280px-wide window
- **AND** uploaded maps are installed, so their rows show Download and Delete actions
- **THEN** the table fits without scrolling sideways, inside the table or on the page

#### Scenario: Long names wrap rather than widen the table

- **WHEN** a map's title, internal name or package name is too long for its column
- **THEN** it wraps within its cell
- **AND** the numeric columns and the row's actions stay on one line

#### Scenario: Narrower desktop window

- **WHEN** the interface is viewed in a desktop window narrower than its content
- **THEN** the page itself does not scroll sideways
- **AND** a table that does not fit scrolls sideways inside its own box

### Requirement: The header shows the panel version and its update state

The header SHALL show the running panel version in square brackets beside the brand, such as `[0.2.0]`: green when no newer release is known, orange reading `[<version> update available]` when one is. When availability is unknown, the version SHALL appear without claiming the install is current or out of date. Activating it SHALL open the panel page.

#### Scenario: Running the latest release

- **WHEN** the interface loads and no newer panel release is available
- **THEN** the header shows `[<running version>]` in green beside the brand
- **AND** activating it opens the panel page

#### Scenario: A newer release is available

- **WHEN** a newer panel release is available
- **THEN** the header shows `[<running version> update available]` in orange
- **AND** activating it opens the panel page within the interface, not the release's page on GitHub

#### Scenario: Availability unknown

- **WHEN** the release check has never succeeded
- **THEN** the header shows `[<running version>]` without an update indication
- **AND** no error is shown in the header
- **AND** activating it opens the panel page

#### Scenario: Update appears while the interface is open

- **WHEN** a newer release is found while a browser has the interface open
- **THEN** the header changes to the update indication without a page reload

### Requirement: Panel upgrades are available from the panel page

The interface SHALL provide a panel page, reached from the header version and not listed in the navigation bar. It SHALL show the installed version, the latest known release, whether an update is available, when the check last ran, a check-now action, a link to the release on GitHub, and the last upgrade's outcome.

#### Scenario: Open the panel page

- **WHEN** the operator activates the header version
- **THEN** the panel page shows the installed version, the latest known release, the update status and when the check last ran
- **AND** the navigation bar does not list the panel page

#### Scenario: Check now

- **WHEN** the operator activates the check-now action
- **THEN** a release check runs
- **AND** the page and the header show its result

#### Scenario: Last check failed

- **WHEN** the most recent release check failed
- **THEN** the page states that the release source could not be reached, with the reason

#### Scenario: Last upgrade failed

- **WHEN** the most recent upgrade failed
- **THEN** the page shows the versions involved, the failure and the helper's diagnostic output

#### Scenario: Reload the panel page

- **WHEN** a browser requests the panel page's route directly
- **THEN** the web interface loads and shows the panel page

### Requirement: One-click upgrade is offered and confirmed on the panel page

When an update is available and one-click upgrade is possible, the panel page SHALL offer an upgrade to the named version. It SHALL require confirmation stating that the game server will restart and players will be disconnected. Without one-click, it SHALL show the manual root command to copy. Upgrade controls SHALL appear only on the panel page.

#### Scenario: Upgrade offered

- **WHEN** an update is available and one-click upgrade is possible
- **THEN** the panel page offers an action to upgrade to the named version
- **AND** activating it asks for confirmation that states the game server will restart and players will be disconnected
- **AND** the upgrade is requested only on confirmation

#### Scenario: Helper not installed

- **WHEN** an update is available but one-click upgrade is not possible
- **THEN** the panel page shows the manual root upgrade command with a copy action
- **AND** no upgrade button is offered

#### Scenario: Upgrade refused

- **WHEN** an upgrade request is refused
- **THEN** the panel page shows the reason returned

#### Scenario: Not while disconnected or busy

- **WHEN** the connection to the panel is lost, a lifecycle transition is in progress, or an upgrade is already in flight
- **THEN** the upgrade action is unavailable

### Requirement: The panel page shows the latest release's notes

The panel page SHALL show the latest known release's notes, formatted from Markdown, with its version and publish date, whether or not it is newer than the running version. Markup in the notes SHALL NOT run script or inject raw HTML, and links in them SHALL open outside the interface. Missing notes SHALL be stated.

#### Scenario: Update available with notes

- **WHEN** a newer release with notes is available
- **THEN** the panel page shows that release's version, publish date and formatted notes

#### Scenario: Running the latest release

- **WHEN** the running version is the latest release
- **THEN** the panel page shows that release's notes

#### Scenario: Notes contain raw HTML

- **WHEN** the release notes contain an HTML tag such as `<script>` or `<img onerror=...>`
- **THEN** it is not rendered as HTML and no script runs

#### Scenario: Release has no notes

- **WHEN** the latest release was published with empty notes
- **THEN** the page states that no release notes were published and still links to the release on GitHub

### Requirement: An in-flight upgrade is shown and followed

While a panel upgrade is pending or running, the interface SHALL show a banner on every page naming the target version and stating that the panel and game server will restart. When the upgraded panel answers with a different version, the interface SHALL reload onto it.

#### Scenario: Upgrade in flight

- **WHEN** an upgrade has been requested and has not finished
- **THEN** every page shows a banner naming the target version

#### Scenario: Upgraded panel comes back

- **WHEN** the panel becomes reachable again reporting a version different from the one the page loaded with
- **THEN** the interface reloads itself onto the new version

#### Scenario: Upgrade fails without a restart

- **WHEN** the upgrade fails and the previous panel keeps running
- **THEN** the banner is cleared
- **AND** the panel page shows the failure
