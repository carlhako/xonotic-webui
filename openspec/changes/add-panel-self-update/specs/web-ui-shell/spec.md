# Spec Delta

## ADDED Requirements

### Requirement: The panel version and its update state are shown in the header

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

#### Scenario: Phone width

- **WHEN** the interface is viewed at a 375px-wide viewport with an update available
- **THEN** the version and its update indication are visible without sideways scrolling

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
