# Spec Delta

## ADDED Requirements

### Requirement: A match counts as played when the player is there at its end

A match SHALL count toward a player's matches played, and can count as a win for them, only
when it ran to its limit and the player was on its final scoreboard as a player when it
ended. When they joined SHALL NOT matter. A match against bots SHALL count like any other.

#### Scenario: Joined part way through

- **WHEN** a player joins a match half way through and is playing when it reaches its limit
- **THEN** their matches played increases by one

#### Scenario: Left before the end

- **WHEN** a player takes part in a match and leaves before it reaches its limit
- **THEN** their matches played is unchanged
- **AND** their frags and other figures from that match are still counted

#### Scenario: Match cut short

- **WHEN** a match a player is in is ended early by a map change or vote
- **THEN** their matches played is unchanged

#### Scenario: Spectating at the end

- **WHEN** a player who took part has moved to spectating when the match reaches its limit
- **THEN** their matches played is unchanged

#### Scenario: Against bots

- **WHEN** a human plays a match against bots to its limit
- **THEN** their matches played increases by one

## MODIFIED Requirements

### Requirement: A player's details are shown in a dialog

Activating a player in the table SHALL open a dialog with that player's full details: name and names used, short key, first and last seen, sessions, matches played, all totals, damage dealt and taken, average ping, a per-weapon table of frags and accuracy, and achievements. It SHALL offer a way to see the matches that player took part in. It SHALL be dismissible and keyboard accessible.

#### Scenario: Open details

- **WHEN** the operator activates a player's row
- **THEN** a dialog shows that player's details and per-weapon statistics

#### Scenario: Matches played shown

- **WHEN** a player has played 12 matches and won 3
- **THEN** the dialog shows 12 matches played and 3 wins

#### Scenario: See the player's matches

- **WHEN** the operator chooses to see a player's matches from their dialog
- **THEN** the Matches section opens filtered to that player

#### Scenario: Close details

- **WHEN** the operator presses Escape or the close control
- **THEN** the dialog closes and the table is shown as it was

#### Scenario: Player without match statistics

- **WHEN** a player has sessions but has never been in an end-of-match report
- **THEN** the dialog shows their time on server and live counts, and states that no match statistics are recorded yet
