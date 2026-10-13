# Spec Delta

## Purpose

Gives the operator a live view of the Xonotic server's console output and a way to send it commands from the browser, as they would at a terminal on the server.

## ADDED Requirements

### Requirement: Console output is streamed live

The panel SHALL deliver each line the server writes to its console to every connected client as it is produced, in order.

#### Scenario: Output appears as produced

- **WHEN** the server writes lines to its console
- **THEN** each connected client receives them in the order written
- **AND** a client does not need to poll

#### Scenario: Multiple clients

- **WHEN** two clients are connected
- **THEN** both receive every line

### Requirement: Recent output is replayed on connect

A client connecting to the console SHALL first receive the most recent buffered output, so that the view is not empty mid-session.

#### Scenario: Client connects mid-session

- **WHEN** a client connects while the server has been producing output
- **THEN** it receives the buffered recent lines before live lines
- **AND** no line is delivered twice

#### Scenario: Buffer is bounded

- **WHEN** the output exceeds the buffer limit
- **THEN** the oldest lines are discarded first
- **AND** memory use does not grow without bound

### Requirement: Output persists across server restarts

The console buffer SHALL be kept when the server stops or restarts, and SHALL mark where each server run begins so that runs can be told apart.

#### Scenario: Server restarted

- **WHEN** the server is restarted
- **THEN** earlier output remains in the buffer
- **AND** a marker line separates the previous run from the new one

### Requirement: Commands are delivered to the server console

The panel SHALL send a submitted command to the running server as if typed at its console, and SHALL reject it if the server is not running.

#### Scenario: Command submitted while running

- **WHEN** a command is submitted while the server is `running`
- **THEN** it is delivered to the server console
- **AND** any resulting output appears in the stream

#### Scenario: Command submitted while stopped

- **WHEN** a command is submitted while the server is not running
- **THEN** it is rejected with an error stating the server is not running
- **AND** nothing is queued

### Requirement: A command is a single line

The panel SHALL reject a command that is empty or contains a line break, so that one submission always produces exactly one console command.

#### Scenario: Multi-line input

- **WHEN** a command containing a line break is submitted
- **THEN** it is rejected
- **AND** nothing is sent to the server

#### Scenario: Empty input

- **WHEN** an empty or whitespace-only command is submitted
- **THEN** it is rejected

### Requirement: Colour codes are rendered, not shown raw

Xonotic embeds colour codes in names and messages. The console SHALL display them as colour, or hide them, and SHALL NOT show the raw code characters.

#### Scenario: Coloured player name

- **WHEN** a console line contains a name with colour codes
- **THEN** the name appears in its colours with no code characters visible

#### Scenario: Escaped caret

- **WHEN** a line contains an escaped caret meant to be literal
- **THEN** a single literal caret is shown
