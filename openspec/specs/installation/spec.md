# installation Specification

## Purpose

Defines how an operator gets the panel and a working Xonotic dedicated server onto a clean Debian machine or LXC with one command, and how re-running that command upgrades or repairs the install without touching server data.

## Requirements

### Requirement: Installation requires root and a supported platform

The installer SHALL refuse to run unless it is run as root on a 64-bit x86 Debian-family system with the `apt` package manager, and SHALL state the reason for any refusal before changing anything.

#### Scenario: Run as a non-root user

- **WHEN** the installer is run by a user other than root
- **THEN** it exits non-zero with a message that root is required
- **AND** it has changed nothing on the system

#### Scenario: Unsupported architecture

- **WHEN** the installer is run on a machine that is not 64-bit x86
- **THEN** it exits non-zero naming the detected architecture and the supported one
- **AND** it has changed nothing on the system

#### Scenario: Insufficient disk space

- **WHEN** the filesystem that will hold the game files has less free space than the game archive and its extracted tree need
- **THEN** the installer exits non-zero stating the space required and available

### Requirement: Services run as an unprivileged dedicated user

The installer SHALL create a dedicated system user with no login shell, and the panel and the Xonotic server it supervises SHALL run as that user and never as root.

#### Scenario: Fresh install creates the user

- **WHEN** the installer completes on a machine without the service user
- **THEN** the service user exists with a non-login shell
- **AND** the running panel process and game server process are owned by that user

#### Scenario: Application files are not writable by the service user

- **WHEN** the installer completes
- **THEN** the installed application and game files are owned by root
- **AND** the service user cannot modify them

### Requirement: The game server is installed from a pinned, verified release

The installer SHALL download one specific, pinned Xonotic release and SHALL refuse to install an archive whose SHA-256 digest does not match the digest pinned in the installer.

#### Scenario: Archive matches the pinned digest

- **WHEN** the downloaded archive's digest equals the pinned digest
- **THEN** the archive is extracted and the game server becomes available to the panel

#### Scenario: Archive does not match

- **WHEN** the downloaded archive's digest differs from the pinned digest
- **THEN** the installer exits non-zero reporting the mismatch
- **AND** no unverified game files are left in the install location

#### Scenario: Offline install from a local archive

- **WHEN** the operator supplies a local game archive path
- **THEN** the installer uses it instead of downloading
- **AND** it still applies the same digest check

### Requirement: The panel is distributed as a self-contained release

The installer SHALL install the panel from a published release artifact whose web interface is prebuilt, and SHALL NOT require Node.js or a compiler on the target machine.

#### Scenario: Install with no build tools present

- **WHEN** the installer runs on a machine with only the base system and network access
- **THEN** it installs every dependency as a prebuilt package
- **AND** the panel starts without any build step

#### Scenario: Pinning a panel release

- **WHEN** the operator selects a specific release tag
- **THEN** that release is installed rather than the latest

### Requirement: Install runs the panel as an enabled service

The installer SHALL install a system service that starts at boot, restarts the panel after a failure, and binds the web port without running the panel as root.

#### Scenario: Service enabled and started

- **WHEN** the installer completes
- **THEN** the panel service is enabled and running
- **AND** the web interface answers on the configured port

#### Scenario: Panel crash

- **WHEN** the panel process exits unexpectedly
- **THEN** the service manager starts it again

### Requirement: Re-running the installer is a safe upgrade or repair

Re-running the installer on an existing install SHALL replace the application and, if missing, the game files, and SHALL leave server configuration, panel state, player history and logs untouched.

#### Scenario: Re-run on a healthy install

- **WHEN** the installer is run again with the same release
- **THEN** the panel is running afterwards
- **AND** the server configuration and panel state are byte-for-byte unchanged
- **AND** the game archive is not downloaded again

#### Scenario: New release does not start

- **WHEN** a re-run installs a release that fails to answer its health check
- **THEN** the previous application version is restored and running
- **AND** the installer exits non-zero explaining the failure

### Requirement: A first-run configuration is seeded and never overwritten

The installer SHALL create a minimal, working server configuration only when none exists, and SHALL never overwrite an existing server configuration.

#### Scenario: Fresh install has a joinable server

- **WHEN** the installer completes on a fresh machine and the server is started
- **THEN** the server runs with a valid configuration
- **AND** the structured event log the panel depends on is enabled

#### Scenario: Existing configuration is kept

- **WHEN** a server configuration already exists at install time
- **THEN** its contents are unchanged after the installer completes

### Requirement: The installer reports the outcome

On completion the installer SHALL print the URL of the web interface and the game port that must be reachable, and SHALL exit zero only if the panel passed its health check.

#### Scenario: Successful install

- **WHEN** the panel passes its health check
- **THEN** the installer prints the web URL using the machine's address and the game UDP port
- **AND** it exits zero

### Requirement: The installer sets up one-click upgrades

The installer SHALL install the privileged upgrade helper and the service that runs it when the panel requests an upgrade, and SHALL enable them. The helper SHALL be bound to the repository the installer itself installed from. Re-running the installer SHALL add or refresh the helper.

#### Scenario: Fresh install

- **WHEN** the installer completes on a fresh machine
- **THEN** the upgrade helper is installed and its trigger is enabled
- **AND** the panel reports one-click upgrade as available

#### Scenario: Upgrading an install made before one-click upgrades

- **WHEN** the installer is re-run on an install that has no upgrade helper
- **THEN** the helper is installed and its trigger is enabled
- **AND** later upgrades can be requested from the panel

#### Scenario: Helper bound to the installing repository

- **WHEN** the installer is run with an alternative release repository
- **THEN** the installed helper fetches releases only from that repository

### Requirement: The service user can request an upgrade but not direct the helper

After installation, the service user SHALL be able to place an upgrade request where the helper reads it, and SHALL be able to read the helper's recorded outcome. It SHALL NOT be able to modify the helper, the service that runs it, or the helper's recorded outcomes.

#### Scenario: Request location is writable by the service user

- **WHEN** the installer completes
- **THEN** the upgrade request location is owned by the service user

#### Scenario: Helper and outcomes are root-owned

- **WHEN** the installer completes
- **THEN** the helper, its service definitions and its outcome location are owned by root
- **AND** the service user can read the outcome location but cannot write to it
