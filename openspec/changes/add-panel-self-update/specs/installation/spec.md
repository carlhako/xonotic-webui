# Spec Delta

## ADDED Requirements

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
