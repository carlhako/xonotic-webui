# Spec Delta

## MODIFIED Requirements

### Requirement: Console output is streamed live

The panel SHALL deliver each line the server writes to its console to every connected client as it is produced, in order. Replies to the panel's own queries and the server's end-of-match statistics report SHALL be withheld from clients and from replayed history.

#### Scenario: Output appears as produced

- **WHEN** the server writes lines to its console
- **THEN** each connected client receives them in the order written
- **AND** a client does not need to poll

#### Scenario: Multiple clients

- **WHEN** two clients are connected
- **THEN** both receive every line

#### Scenario: Statistics report withheld

- **WHEN** the server prints its end-of-match statistics report
- **THEN** no client receives the report's lines, live or on replay
- **AND** the ordinary match-end lines around it are delivered as usual
