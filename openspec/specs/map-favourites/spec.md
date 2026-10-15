# map-favourites Specification

## Purpose

Lets the operator mark maps as favourites and narrow the map views to just those, so the maps used most are quick to find among a long catalogue.

## Requirements

### Requirement: A map can be starred as a favourite

The panel SHALL let the operator star and unstar any listed map from the map card view and from the table view, and SHALL show each map's starred state in both. The star SHALL be a toggle on every map.

#### Scenario: Star a map

- **WHEN** the operator stars `boil` in the card view
- **THEN** `boil` is shown starred in the card view
- **AND** `boil` is shown starred in the table view

#### Scenario: Unstar a map

- **WHEN** the operator unstars `boil` in the table view
- **THEN** `boil` is shown not starred in both views

#### Scenario: Failed change

- **WHEN** starring a map fails because the panel cannot be reached
- **THEN** the star is shown as it was
- **AND** an error is shown

### Requirement: Favourites are kept by the panel and shared

The panel SHALL store the favourites itself, keyed by map name, so that they persist across page reloads, browsers and panel restarts, and are the same for every client.

#### Scenario: Another browser

- **WHEN** the operator stars `boil` in one browser and opens the Maps section in another
- **THEN** `boil` is shown starred in the second browser

#### Scenario: Panel restart

- **WHEN** the panel is restarted
- **THEN** the favourites are unchanged

#### Scenario: Server stopped

- **WHEN** the operator stars a map while the game server is stopped
- **THEN** the favourite is kept

### Requirement: Maps can be filtered to favourites only

Both Maps views SHALL offer a single "favourites only" filter at the top that, when on, lists only starred maps in whichever view is shown. It SHALL combine with the gametype filter of the card view, listing only maps that satisfy both.

#### Scenario: Filter on

- **WHEN** `boil` and `warfare` are starred and the operator turns favourites only on
- **THEN** only `boil` and `warfare` are listed

#### Scenario: Applies to both views

- **WHEN** favourites only is on and the operator switches to the other view
- **THEN** the other view also lists only the starred maps
- **AND** the filter is still shown as on

#### Scenario: Combined with the gametype filter

- **WHEN** favourites only is on and the card view is filtered to Capture the Flag
- **THEN** only starred maps that support Capture the Flag are listed

#### Scenario: No favourites

- **WHEN** favourites only is on and nothing is starred
- **THEN** the view says there are no favourites yet and how to add one

### Requirement: Favourites of maps that are no longer installed do not appear

A favourite whose map is not installed SHALL NOT be listed and SHALL NOT cause an error. If the map is installed again it SHALL be starred again.

#### Scenario: Package deleted

- **WHEN** `mymap` is starred and its package is deleted
- **THEN** `mymap` is not listed in either view and no error is shown

#### Scenario: Installed again

- **WHEN** the package containing `mymap` is uploaded again
- **THEN** `mymap` is listed starred
