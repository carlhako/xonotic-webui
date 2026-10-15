# map-packages Specification

## Purpose

Lets the operator add, fetch back and remove map packages in the panel's user data directory from the web interface, with validation so that only usable map packages are installed.

## Requirements

### Requirement: A map package can be uploaded

The panel SHALL let the operator upload a `.pk3` map package, which is installed in the user data directory and whose maps are then listed. Only the `.pk3` file type SHALL be accepted. The upload SHALL report the maps it contains.

#### Scenario: Valid package

- **WHEN** the operator uploads `mymap_v2.pk3`, a package containing the map `mymap`
- **THEN** the package is installed
- **AND** the result names `mymap`
- **AND** `mymap` appears in the map list

#### Scenario: Other file types

- **WHEN** the operator uploads `maps.zip`, `mymap.bsp` or a file with no extension
- **THEN** the upload is rejected with an error stating that only `.pk3` files are accepted
- **AND** nothing is installed

#### Scenario: Uploaded while the server is stopped

- **WHEN** the operator uploads a valid package while the server is stopped
- **THEN** the package is installed and its maps are listed

### Requirement: Uploads are validated before they are installed

The panel SHALL reject an upload whose file name is unsafe, whose size exceeds 256 MB, that is not a readable package, or that contains no map. A rejected upload SHALL leave nothing installed, and the error SHALL say which check failed.

#### Scenario: Unsafe file name

- **WHEN** the operator uploads a file named `../evil.pk3`, or one containing a path separator, a space or a leading dot
- **THEN** the upload is rejected with an error stating that the file name is not allowed
- **AND** nothing is written outside the user data directory

#### Scenario: Too large

- **WHEN** the operator uploads a `.pk3` larger than 256 MB
- **THEN** the upload is rejected with an error stating the size limit
- **AND** no partial file is left behind

#### Scenario: Not a package

- **WHEN** the operator uploads a file named `fake.pk3` that is not a valid package
- **THEN** the upload is rejected with an error stating that it is not a valid package

#### Scenario: No map in the package

- **WHEN** the operator uploads a valid package that contains no map
- **THEN** the upload is rejected with an error stating that it contains no map

#### Scenario: Interrupted upload

- **WHEN** the connection drops partway through an upload
- **THEN** nothing is installed and no partial file remains

### Requirement: An existing package is not replaced

The panel SHALL reject an upload whose file name is already installed in the user data directory. The operator replaces a package by deleting it first.

#### Scenario: Same name

- **WHEN** the operator uploads `mymap_v2.pk3` while a package of that name is installed
- **THEN** the upload is rejected with an error stating that the file already exists
- **AND** the installed package is unchanged

### Requirement: An upload that shadows an installed map is flagged

The panel SHALL tell the operator when an uploaded package contains a map whose name is already installed from another package, since the user data directory takes precedence over the game's own packages.

#### Scenario: Map name already installed

- **WHEN** the operator uploads a package containing a map named `boil`, which the game provides
- **THEN** the upload succeeds
- **AND** the result states that `boil` has the same name as an installed map and that the uploaded one is used

### Requirement: A newly installed package is marked as needing a restart

A package installed while the server is running SHALL be marked as not yet loaded by the game, and its maps SHALL NOT be offered for going to, until the server has been restarted. The interface SHALL say so.

#### Scenario: Uploaded while running

- **WHEN** the operator uploads a package while the server is running
- **THEN** its maps are listed with a note that a server restart is needed
- **AND** going to one of them is not offered

#### Scenario: Go to attempted anyway

- **WHEN** a request is made to go to a map whose package has not yet been loaded by the game
- **THEN** it is rejected with an error stating that the server must be restarted first
- **AND** the current match continues

#### Scenario: After a restart

- **WHEN** the server is restarted after the upload
- **THEN** the maps are listed without the note
- **AND** they can be gone to when they support the current gametype

### Requirement: Installed packages are listed with their size

The panel SHALL show, for each installed map, the package file it comes from and that file's size, and whether the package is in the user data directory or part of the game. The game's own packages SHALL NOT be offered for deletion or download.

#### Scenario: User package

- **WHEN** the operator opens the map list
- **THEN** each map from an uploaded package shows that package's file name and its size

#### Scenario: Game package

- **WHEN** a map comes from the game's own packages
- **THEN** it is identified as part of the game
- **AND** no delete or download is offered for it

### Requirement: A map package can be downloaded

The panel SHALL let the operator download an installed package from the user data directory, byte for byte as installed.

#### Scenario: Download

- **WHEN** the operator downloads `mymap_v2.pk3`
- **THEN** the browser receives a file of that name with the same content as the installed package

#### Scenario: Not a user package

- **WHEN** a download is requested for a name that is not a package in the user data directory, including a game package or a path
- **THEN** the request is rejected with an error stating the package was not found

### Requirement: A map package can be deleted after confirmation

The panel SHALL let the operator delete a package from the user data directory. The interface SHALL ask for confirmation first, naming the file and every map in it, and SHALL say which of those maps are in the rotation.

#### Scenario: Confirm

- **WHEN** the operator chooses delete on `mymap_v2.pk3`
- **THEN** a popup asks for confirmation, naming the file and its maps
- **AND** the package is deleted only on confirmation

#### Scenario: Cancel

- **WHEN** the operator cancels the popup
- **THEN** the package is still installed

#### Scenario: Map in the rotation

- **WHEN** the operator deletes a package whose map is in the rotation
- **THEN** the popup states that the map is in the rotation
- **AND** after deletion the rotation shows the map as not installed

#### Scenario: Game package or unknown name

- **WHEN** a delete is requested for a game package, a path, or a name that is not installed
- **THEN** the request is rejected with an error stating the package was not found
- **AND** no file is removed

#### Scenario: Map from a deleted package shadowed a game map

- **WHEN** the deleted package contained a map that replaced a game map of the same name
- **THEN** the game's map of that name is listed again

### Requirement: Package changes are not offered without a connection

The interface SHALL NOT offer upload, delete or download while the panel is disconnected from the server, and SHALL report a failed request instead of appearing to succeed.

#### Scenario: Request fails

- **WHEN** a delete is requested and the panel cannot be reached
- **THEN** the interface shows the error
- **AND** the package is still listed
