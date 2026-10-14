# Spec Delta

## Purpose

Keeps the panel itself current. It finds out whether a newer stable panel release has been published, and upgrades the installed panel in place when the operator asks. A privileged helper does the upgrade. The panel can ask it to act, but can only name an official release.

## ADDED Requirements

### Requirement: The running panel version is reported

The panel SHALL report the version of the panel that is currently running through the programmatic interface.

#### Scenario: Version is requested

- **WHEN** a client requests the panel's version information
- **THEN** the running panel version is returned
- **AND** it is the version of the code actually executing, not a value read from a separately editable file

### Requirement: Availability of a newer panel release is determined

The panel SHALL determine the latest stable release from the project's published releases and compare it with the running version. It SHALL report whether an update is available, the latest version, a link to that release's page, and when the check last ran. Drafts and pre-releases SHALL NOT be treated as available updates.

#### Scenario: A newer release exists

- **WHEN** the latest stable release is a higher version than the running version
- **THEN** an update is reported as available
- **AND** the latest version and a link to its release page are reported

#### Scenario: Running the latest release

- **WHEN** the latest stable release is the same version as the running version
- **THEN** no update is reported as available

#### Scenario: Running a version newer than the latest release

- **WHEN** the running version is higher than the latest stable release (for example, a development build)
- **THEN** no update is reported as available

#### Scenario: Only a pre-release is newer

- **WHEN** the only release newer than the running version is a draft or pre-release
- **THEN** no update is reported as available

#### Scenario: A release tag that is not a version

- **WHEN** the latest release's tag is not of the form `vMAJOR.MINOR.PATCH`
- **THEN** no update is reported as available
- **AND** the check is reported as failed with the reason

### Requirement: The latest release's details are reported

With the latest stable release, the panel SHALL report its title, publish date and release notes as published (Markdown text), whether or not that release is newer than the running version. Release notes that were published empty SHALL be reported as absent rather than as an empty string.

#### Scenario: Notes of the running release

- **WHEN** the running version is the latest stable release
- **THEN** that release's title, publish date and notes are still reported

#### Scenario: Release published without notes

- **WHEN** the latest stable release has empty or whitespace-only notes
- **THEN** the release is reported normally
- **AND** its notes are reported as absent

### Requirement: Release checks are periodic, shared, and bounded

The panel SHALL check for a newer release shortly after it starts and then periodically. It SHALL serve the most recent result to all clients from a single cached check rather than contacting the release source per client request. An operator SHALL be able to request an immediate check.

#### Scenario: Panel starts

- **WHEN** the panel starts
- **THEN** a release check is performed without delaying the game server's start or the web interface

#### Scenario: Many clients view the interface

- **WHEN** several browsers display the interface at the same time
- **THEN** they are all served the same cached result
- **AND** the release source is not contacted once per browser

#### Scenario: Operator requests a check

- **WHEN** an operator requests an immediate release check
- **THEN** a check is performed and its result replaces the cached result

#### Scenario: Result survives a restart

- **WHEN** the panel restarts while the release source is unreachable
- **THEN** the last successful result is reported until a new check succeeds

#### Scenario: Release checks are disabled

- **WHEN** the operator has disabled release checks in the panel's configuration
- **THEN** the release source is never contacted
- **AND** update availability is reported as unknown unless an operator requests a check

### Requirement: An unreachable release source is not an error condition for the operator

When the release source cannot be reached or returns an unusable response, the panel SHALL report update availability as unknown, or as the last successful result if one exists. It SHALL log the failure, make its reason available to the interface, and continue operating normally.

#### Scenario: No internet access

- **WHEN** a release check fails because the release source is unreachable
- **THEN** update availability is reported as unknown, or as the last successful result if one exists
- **AND** the failure reason is available to the interface
- **AND** no other panel function is affected

#### Scenario: Rate limited

- **WHEN** the release source refuses the request
- **THEN** the check is reported as failed with the reason
- **AND** the last successful result is kept

#### Scenario: Requests identify a client

- **WHEN** the panel contacts the release source
- **THEN** the request identifies a client agent that includes the running panel version

### Requirement: Whether one-click upgrade is possible is reported

The panel SHALL report whether the privileged upgrade helper is installed on the host. When it is not, the panel SHALL report the command an operator can run as root to upgrade manually.

#### Scenario: Helper installed

- **WHEN** the upgrade helper is installed
- **THEN** one-click upgrade is reported as available

#### Scenario: Helper absent

- **WHEN** the upgrade helper is not installed (for example, an install made before this capability existed)
- **THEN** one-click upgrade is reported as unavailable
- **AND** the manual root upgrade command is reported

### Requirement: An upgrade can be requested for the reported release

The panel SHALL let an operator request an upgrade to the release reported as available. The request SHALL name that exact release version, not "whatever is latest" when the helper runs. The panel SHALL acknowledge the request once it has been handed to the helper.

#### Scenario: Upgrade requested

- **WHEN** an operator requests an upgrade to the reported version while an update is available and the helper is installed
- **THEN** the panel records an upgrade request naming that exact release version
- **AND** the request is acknowledged and the upgrade is reported as pending

#### Scenario: A newer release is published after the check

- **WHEN** a further release is published between the check and the helper acting
- **THEN** the release named in the request is installed, not the later one

### Requirement: Upgrade requests that cannot proceed are refused

The panel SHALL refuse an upgrade request, with a distinguishable reason and without recording a request, when no update is available, when the requested version is not the one reported, when the helper is not installed, when an upgrade is already pending or running, or while a server start, stop or restart is in progress.

#### Scenario: Nothing to upgrade to

- **WHEN** an upgrade is requested while no update is reported as available
- **THEN** the request is refused with a distinguishable reason

#### Scenario: Version mismatch

- **WHEN** an upgrade is requested for a version other than the one reported as available
- **THEN** the request is refused with a distinguishable reason

#### Scenario: Helper not installed

- **WHEN** an upgrade is requested while the helper is not installed
- **THEN** the request is refused with a distinguishable reason

#### Scenario: Already pending

- **WHEN** an upgrade is requested while an earlier upgrade request is pending or running
- **THEN** the request is refused
- **AND** at most one upgrade runs at a time

#### Scenario: Lifecycle transition in progress

- **WHEN** an upgrade is requested while the game server is starting, stopping or restarting
- **THEN** the request is refused with a distinguishable reason

### Requirement: The upgrade is performed by a privileged helper the panel cannot direct

A helper with the privileges to replace the panel's installation SHALL do the upgrade, and the panel SHALL NOT gain them. The helper SHALL accept from the panel only a well-formed release version and request id, echoed in every outcome it records. It SHALL fetch only from the repository fixed at install time.

#### Scenario: Well-formed request

- **WHEN** the helper receives a request naming a well-formed release version
- **THEN** it downloads that release's installer and application package from the official release
- **AND** it runs that release's installer to upgrade in place

#### Scenario: Malformed request

- **WHEN** the helper receives a request that is not a well-formed release version and request id, is oversized, or is not a regular file
- **THEN** nothing is downloaded or installed
- **AND** the request is recorded as rejected

#### Scenario: Panel remains unprivileged

- **WHEN** the panel is running normally
- **THEN** it cannot modify its installation directory, its service definition, the helper, or the helper's recorded outcomes

### Requirement: Downloaded upgrade files are verified before use

The helper SHALL verify each downloaded file against the sha256 digest published with the release before running or installing anything. It SHALL fail closed when a digest is missing or differs.

#### Scenario: Checksum mismatch

- **WHEN** a downloaded file does not match its published digest
- **THEN** nothing is installed
- **AND** the upgrade is recorded as failed

#### Scenario: Digest not published

- **WHEN** the release does not publish a digest for a required file
- **THEN** nothing is installed
- **AND** the upgrade is recorded as failed

### Requirement: An upgrade preserves the game server's running intent

Requesting an upgrade SHALL NOT itself stop the game server. Completing an upgrade SHALL restart the panel, which shuts the game server down cleanly. After the restart, the game server SHALL be running if and only if it was intended to be running before the upgrade.

#### Scenario: Server was running

- **WHEN** an upgrade is requested while the game server is running
- **THEN** the game server keeps running while the release is downloaded and verified
- **AND** it is shut down cleanly when the panel restarts
- **AND** it is running again once the upgraded panel has started

#### Scenario: Server was stopped

- **WHEN** an upgrade completes while the game server was intentionally stopped
- **THEN** it remains stopped after the upgraded panel has started

### Requirement: The upgrade outcome is recorded and reported

The outcome of the most recent upgrade SHALL be recorded durably and reported by the panel after it restarts. It SHALL include the versions upgraded from and to, whether it succeeded, when it finished, and diagnostic output on failure. A failed upgrade SHALL leave the previous panel running.

#### Scenario: Upgrade succeeds

- **WHEN** an upgrade completes successfully
- **THEN** the upgraded panel reports the previous and new versions, success, and the completion time

#### Scenario: Upgrade fails before installation

- **WHEN** an upgrade fails during download or verification
- **THEN** the previously installed panel continues running
- **AND** the failure and its diagnostic output are reported

#### Scenario: New release does not come up

- **WHEN** the installed release fails its health check and the installer restores the previous version
- **THEN** the previous panel is running
- **AND** the upgrade is reported as failed with the installer's output

#### Scenario: Upgrade is in progress

- **WHEN** an upgrade request is pending or running
- **THEN** the panel reports that an upgrade is in progress

#### Scenario: Retrying after a failed attempt

- **WHEN** an upgrade to a version is requested again after an earlier attempt at the same version failed
- **THEN** the earlier attempt's outcome is not reported as the outcome of the new request

#### Scenario: A slow installation

- **WHEN** the helper is still installing (for example, downloading a new game release) when the panel would otherwise give up waiting, including after the upgraded panel has started
- **THEN** the panel keeps following the helper for as long as the helper may run
- **AND** a successful installation is reported as a success

### Requirement: Every published release carries release notes from the changelog

The project SHALL keep a changelog in the repository with one section per released version. Publishing a release SHALL use that version's changelog section as the release's notes. A release whose version has no changelog section, or an empty one, SHALL NOT be published.

#### Scenario: Tag with a changelog entry

- **WHEN** a version tag is pushed and the changelog has a non-empty section for that version
- **THEN** the release is published with that section's text as its notes

#### Scenario: Tag without a changelog entry

- **WHEN** a version tag is pushed and the changelog has no section, or an empty section, for that version
- **THEN** the release is not published
- **AND** the publishing job fails with a message naming the missing version

#### Scenario: Dry run checks the entry

- **WHEN** the release workflow is run manually without a tag
- **THEN** it checks the changelog section for the version declared in the project metadata
- **AND** it fails, naming the version, if that section is missing or empty
