# Spec Delta

## ADDED Requirements

### Requirement: Map voting has an enable switch

The Voting group SHALL show a "Voting enabled" switch. While it is off, the map-vote settings SHALL be shown but not editable. Saving with it off SHALL disable the map vote, so the server plays the next map in the rotation; saving with it on SHALL enable the vote with the chosen number of maps.

#### Scenario: Voting is on

- **WHEN** the operator opens the Voting group and the server has a non-zero map-vote count
- **THEN** the switch is on
- **AND** "Maps in the vote" and "Vote length" are editable

#### Scenario: Voting is off

- **WHEN** the operator opens the Voting group and map voting is disabled
- **THEN** the switch is off
- **AND** "Maps in the vote" and "Vote length" are shown greyed out and cannot be edited

#### Scenario: Turning voting off

- **WHEN** the operator turns the switch off and saves
- **THEN** map voting is disabled
- **AND** the change is reported as taking effect at the next map
- **AND** the next match is chosen from the map rotation without a vote

#### Scenario: Turning voting on

- **WHEN** the operator turns the switch on, leaves the number of maps at 6 and saves
- **THEN** map voting is enabled with 6 maps

### Requirement: The map-vote count is kept while voting is off

While the switch is off, the number of maps SHALL show the last non-zero count seen in this browser session instead of 0. Turning the switch on again SHALL restore that count, or the setting's default when none was seen.

#### Scenario: Count restored

- **WHEN** the map-vote count is 10, the operator turns the switch off and then on again
- **THEN** "Maps in the vote" is 10 again
- **AND** nothing is saved until the operator saves

#### Scenario: Count shown while off

- **WHEN** the operator turns the switch off with the count at 10
- **THEN** "Maps in the vote" shows 10, greyed out, not 0

#### Scenario: No count remembered

- **WHEN** the operator opens the Voting group with voting already disabled and turns the switch on
- **THEN** "Maps in the vote" shows the default of 6

### Requirement: Zero maps is not accepted while voting is on

While the switch is on, a map-vote count below 1 SHALL be refused on the field with a message that says to turn voting off with the switch. The refusal SHALL be made before anything is sent to the server.

#### Scenario: Zero typed while on

- **WHEN** the switch is on and the operator enters 0 for "Maps in the vote" and saves
- **THEN** the field shows an error saying to turn voting off with the switch
- **AND** nothing is saved
