# Spec Delta

## ADDED Requirements

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

## REMOVED Requirements

### Requirement: The interface is usable on a phone

**Reason**: The panel is only used from a desktop browser. Building for a 375px viewport kept every page at 960px, too narrow for the Maps file table.
**Migration**: None. Use a desktop browser; see "The interface is laid out for a desktop browser".

### Requirement: The panel version and its update state are shown in the header

**Reason**: Its phone-width scenario no longer applies, and a scenario cannot be dropped through MODIFIED.
**Migration**: None. Re-added as "The header shows the panel version and its update state" with the same text and every other scenario unchanged.
