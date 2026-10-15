# Design

## Context

Map voting is the curated int `g_maplist_votable` (0 disables the vote, otherwise the
number of maps offered, max 20) plus `g_maplist_votable_timeout`. Both live in the
`voting` group of the registry and are rendered by the generic `Field` in `Settings.tsx`.
The form is edit-then-save: edits are held per key in `SettingsPanel` state, a field is
dirty when its edit is not `undefined`, `null` means "use the default", and Save sends only
the dirty keys. `SettingsPanel` is keyed by tab, so its state is dropped when the operator
switches groups.

`value_labels` is the existing precedent for describing a special numeric value as data
(`0` = "Voting off"). The switch builds on it rather than hard-coding the voting cvar in
the UI. See proposal.md for the motivation and the requirement texts in
`specs/server-settings/spec.md`.

## Goals / Non-Goals

**Goals:**

- One obvious control for "voting on/off" with the dependent fields visibly inactive.
- No change to what is written to the game: still `g_maplist_votable <n>`.
- The mechanism is reusable by another "0 means off" setting without UI changes.

**Non-Goals:**

- A new cvar, a new endpoint, or any server-side storage for the remembered count.
- Changing how the raw cvar editor or the API treat `0`.
- Converting the match limits to switches (a different "off" semantics, "map default" and
  "no limit").

## Decisions

### D1. The switch is metadata on the curated setting

`CuratedSetting` gains an optional `switch`:

```
Switch(
    label="Voting enabled",
    help="...",
    off_value=0,
    enables=("g_maplist_votable_timeout",),
)
```

It sits on `g_maplist_votable`, which is both the master setting (its count is the field
that is greyed) and the carrier of the off value. The API's setting model gets a matching
nullable `switch {label, help, off_value, enables}`.

*Alternatives.* Hard-coding `g_maplist_votable` in `Settings.tsx` is less code but puts a
cvar name in the UI and does not extend. A separate synthetic "setting" for the switch
would need a fake key that is not a cvar and special handling through the save, defaults
and validation paths. Metadata on the real setting keeps one key, one value, one save
path.

### D2. A consistency check at import

The registry asserts at import time that every key in `enables` exists, is in the same
group as its master, is not itself a master, and that `off_value` is an int within
`[min, max]` of an `int` master. A mistake then fails the test run rather than rendering a
broken form. A unit test pins the voting entry.

### D3. Rendering: switch row, then the count, dependents just inactive

In a group, a setting with a `switch` renders as a switch row (label and help from the
switch) immediately followed by its own count field. Dependents are rendered where the
registry puts them and receive `disabled` when their master is off. Nothing is hidden, so
the layout does not jump when the switch is flipped.

The switch state is derived, not stored: on when the shown value of the master
(`edit ?? saved ?? default`, with `null` resolving to the default) differs from
`off_value`. Flipping it writes an edit on the master key only.

| Action | Edit written on `g_maplist_votable` | Count field shows |
| --- | --- | --- |
| switch off | `"0"` (the off value), and the current count is remembered | the remembered count, greyed |
| switch on, a count remembered | the remembered count | that count, editable |
| switch on, none remembered | `null` (use default) | the default (6), editable |

If the default is itself the off value, the fallback is the master's `min` raised to the
first non-off value instead. Today the default is 6, so this is only for the check to stay
total.

Pending edits to dependents are kept while the switch is off and are saved with the
group, which is what the operator would expect from a form.

### D4. The remembered count is browser-session state

It is a map of key to last non-off value, held in the `Settings` component (above the
per-tab `SettingsPanel`, so it survives switching tabs) and filled when the switch is
turned off. After a reload with voting already off nothing is remembered and the default
is offered; the proposal accepts this.

*Alternatives.* `localStorage` would survive reloads but is per-browser, so two operators
would see different "remembered" counts for a value that belongs to the server; a
server-side stash needs a second stored value and API for little gain.

### D5. Zero is refused client-side while on

`toWire` for a master with a switch rejects the off value when the switch is on, with
"Maps in the vote must be 1 or more; turn voting off with the switch". The number input's
`min` is raised to `max(min, 1)` while on. The raw API and the server still accept `0`;
the guard exists so that the number field cannot silently flip the switch off.

## Risks / Trade-offs

- [The remembered count is lost on reload] → It only affects convenience, and the default
  is a sensible fallback. Documented as accepted in the proposal.
- [Two UI paths now reach the same cvar: the switch and typing 0] → The guard in D5 makes
  the switch the only way, and the raw cvar editor is the documented escape hatch.
- [`server.cfg` also sets `g_maplist_votable`] → The existing "also set in server.cfg"
  badge is unaffected; the panel's value still wins, so the switch state reflects the
  panel's effective value.
- [The API model gains a field] → Additive; `web/openapi.json` is regenerated and the
  snapshot test pins it.

## Migration Plan

No data migration: stored values are unchanged and an existing `0` simply loads as switch
off. Rollback is reverting the change.
