# server-lifecycle Specification

## Purpose

Defines how the panel starts, stops, restarts and supervises the Xonotic dedicated server process, including readiness, crash recovery and behaviour across panel restarts.

## Requirements

### Requirement: The server has one of four lifecycle states

The panel SHALL report the server as exactly one of `stopped`, `starting`, `running` or `stopping`, and SHALL move between them only through the transitions below.

#### Scenario: Initial state

- **WHEN** the panel starts and the server has not been started
- **THEN** the state is `stopped`

#### Scenario: Start requested

- **WHEN** a start is accepted
- **THEN** the state becomes `starting`
- **AND** it becomes `running` only when the server signals readiness

#### Scenario: Stop requested

- **WHEN** a stop is accepted on a running server
- **THEN** the state becomes `stopping`
- **AND** it becomes `stopped` when the process has exited

### Requirement: Start launches the dedicated server with the panel's data directory

On start the panel SHALL launch the installed Xonotic dedicated server binary using the configured game port and a data directory owned by the service user, and SHALL fail with a clear error if no game installation is present.

#### Scenario: Normal start

- **WHEN** a start is requested while stopped
- **THEN** the dedicated server process is spawned with the configured port and data directory
- **AND** its configuration is read from that data directory

#### Scenario: Game files missing

- **WHEN** a start is requested and no Xonotic installation exists
- **THEN** the request fails with an error stating that the game is not installed
- **AND** the state remains `stopped`

### Requirement: Readiness is detected from server output

The panel SHALL consider the server ready when it observes the server's startup-complete output, and SHALL treat a server that is not ready within a configured timeout as a failed start.

#### Scenario: Server becomes ready

- **WHEN** the startup-complete output is observed within the timeout
- **THEN** the state becomes `running`

#### Scenario: Server never becomes ready

- **WHEN** the timeout elapses without startup-complete output
- **THEN** the panel stops the process
- **AND** the state returns to `stopped`
- **AND** the failure is reported with the reason

#### Scenario: Process exits during startup

- **WHEN** the server process exits before becoming ready
- **THEN** the state becomes `stopped`
- **AND** the exit is recorded as a failed start

### Requirement: Stop is graceful and bounded

A stop SHALL first ask the server to quit through its console and wait up to a configured timeout for it to exit, and SHALL then terminate the process forcibly if it has not.

#### Scenario: Server exits on request

- **WHEN** a stop is requested and the server quits within the timeout
- **THEN** the state becomes `stopped`
- **AND** the exit is recorded as a requested stop, not a crash

#### Scenario: Server ignores the quit request

- **WHEN** the server is still running when the timeout elapses
- **THEN** the process is forcibly terminated
- **AND** the state becomes `stopped`

### Requirement: Restart is a stop followed by a start

A restart SHALL stop the server as above and then start it, and SHALL be reported as a single operation in progress.

#### Scenario: Restart a running server

- **WHEN** a restart is requested while running
- **THEN** the server is stopped and then started
- **AND** the state passes through `stopping` and `starting` and ends `running`

#### Scenario: Restart a stopped server

- **WHEN** a restart is requested while stopped
- **THEN** the server is started

### Requirement: Conflicting operations are rejected

The panel SHALL reject a lifecycle request that cannot apply in the current state, and SHALL NOT let two lifecycle operations run at once.

#### Scenario: Start while running

- **WHEN** a start is requested while `running` or `starting`
- **THEN** the request is rejected as already running
- **AND** the server is not disturbed

#### Scenario: Stop while stopped

- **WHEN** a stop is requested while `stopped`
- **THEN** the request is rejected as not running

#### Scenario: Request during a transition

- **WHEN** a lifecycle request arrives while another is in progress
- **THEN** it is rejected as a transition in progress

### Requirement: Unexpected exits are restarted with a bound

When the server exits unexpectedly while it should be running, the panel SHALL start it again, and SHALL stop trying and report the condition when it has crashed more than a configured number of times within a configured window.

#### Scenario: Single crash

- **WHEN** the server exits unexpectedly once
- **THEN** the panel starts it again
- **AND** the crash is recorded with its time and exit status

#### Scenario: Crash loop

- **WHEN** the number of crashes within the window exceeds the threshold
- **THEN** the panel stops restarting it
- **AND** the state is `stopped`
- **AND** status reports that automatic restart was abandoned

#### Scenario: Restart limiting disabled

- **WHEN** the threshold is configured as zero
- **THEN** the panel does not restart the server automatically

### Requirement: Intended run state survives panel restarts

The panel SHALL remember whether the operator last left the server started or stopped, and SHALL on panel start restore that state.

#### Scenario: Panel restarts with the server meant to be running

- **WHEN** the panel starts and the server was running when the panel last stopped
- **THEN** the panel starts the server

#### Scenario: Server was deliberately stopped

- **WHEN** the panel starts and the operator had stopped the server
- **THEN** the server is left stopped

### Requirement: Panel shutdown stops the server cleanly

When the panel is asked to shut down, it SHALL stop the server gracefully before exiting, within the same bounded timeout, and SHALL NOT leave an orphaned server process.

#### Scenario: Service stop

- **WHEN** the panel service is stopped while the server is running
- **THEN** the server is asked to quit and exits
- **AND** no server process remains after the panel exits
