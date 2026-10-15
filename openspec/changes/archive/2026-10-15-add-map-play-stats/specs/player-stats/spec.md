## ADDED Requirements

### Requirement: Maps accumulate play totals from the match history

The panel SHALL total, for every map, the matches played on it, the frags scored on it and when it was last played, from the recorded match history. A match SHALL count as played when it ran to its limit and had at least one recorded participant. Frags SHALL include every frag recorded on the map, whether or not the match finished and whoever scored it, bots included.

#### Scenario: Finished match

- **WHEN** a match on `boil` runs to its limit with players in it
- **THEN** the played total of `boil` increases by one
- **AND** the frags scored in it are added to the frag total of `boil`

#### Scenario: Match cut short

- **WHEN** a match on `boil` is ended early by a map change
- **THEN** it does not add to the played total of `boil`
- **AND** its frags are still added to the frag total of `boil`
- **AND** it counts as the last time `boil` was played

#### Scenario: Bots

- **WHEN** a bot frags a human or another bot on `boil`
- **THEN** that frag is part of the frag total of `boil`

#### Scenario: Match with nobody in it

- **WHEN** a match runs to its limit with no recorded participant
- **THEN** it does not add to the played total of its map

#### Scenario: Map never played

- **WHEN** a map has no recorded matches
- **THEN** its played and frag totals are zero
- **AND** it has no last-played time

#### Scenario: Totals survive restarts

- **WHEN** the panel restarts
- **THEN** every map's totals are the same as before the restart

### Requirement: A map's play details are available from the API

The panel SHALL provide one installed map's details: matches played, matches cut short, total frags, first and last played, matches played per gametype, and the ten players with the most frags on that map, each with their name, frags and whether they are a bot. Players with equal frags SHALL be ordered by name.

#### Scenario: Details of a played map

- **WHEN** the details of `boil` are requested
- **THEN** its played and cut-short counts, frag total, first and last played, per-gametype counts and top fraggers are returned
- **AND** the top fraggers are ordered by frags on `boil`, highest first

#### Scenario: Bot among the top fraggers

- **WHEN** a bot is among the ten players with the most frags on the map
- **THEN** it is listed and marked as a bot

#### Scenario: Gametype not recorded

- **WHEN** a counted match has no recorded gametype
- **THEN** it is grouped under an unknown gametype

#### Scenario: Map never played

- **WHEN** the details of an installed map with no recorded matches are requested
- **THEN** zero counts and empty lists are returned, not an error

#### Scenario: Unknown map

- **WHEN** the details of a map that is not installed are requested
- **THEN** a not-found error is returned

#### Scenario: History not recorded

- **WHEN** player history is not being recorded and a map's details are requested
- **THEN** an error states that player history is unavailable
