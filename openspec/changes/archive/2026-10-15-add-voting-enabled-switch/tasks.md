# Tasks

## 1. Registry and API

- [x] 1.1 Add a frozen `Switch` dataclass (`label`, `help`, `off_value`, `enables`) and an optional `switch` field on `CuratedSetting` in `registry.py`; set it on `g_maplist_votable` with label "Voting enabled", `off_value=0` and `enables=("g_maplist_votable_timeout",)`. Verify `tests/test_registry.py` still passes.
- [x] 1.2 Add the import-time consistency check from design D2 (enabled keys exist, same group, not themselves masters; `off_value` is an int in range of an int master). Verify with new registry tests: the voting entry is as specified, and each rule rejects a bad definition.
- [x] 1.3 Add `SwitchModel` and a nullable `switch` on `SettingModel` in `api/schemas.py`, filled in `_setting_model` in `api/settings.py`. Verify with a test in `tests/test_api_settings.py` that `g_maplist_votable` reports its switch and an ordinary setting reports `null`.
- [x] 1.4 Regenerate `web/openapi.json` (`.venv/bin/python scripts/export_openapi.py`) and `web/src/api/schema.d.ts` (`npm --prefix web run gen:api`). Verify `tests/test_openapi_snapshot.py` passes and `npm --prefix web run build` type-checks.

## 2. Settings UI

- [x] 2.1 Add `switch` (`null` by default) to the `makeSetting` helper in `web/src/test/util.tsx`, and add a voting fixture (count, timeout with the switch) to `web/src/test/settings.test.tsx`. Verify the existing settings tests still pass.
- [x] 2.2 In `Settings.tsx`, render a setting that has a `switch` as a switch row followed by its count field; disable the count and the `enables` dependents while the switch is off. Verify with tests: on when the count is non-zero, off and greyed when `0`, and the fields are editable again when turned on.
- [x] 2.3 Write the edits per design D3 (off writes the off value and remembers the count; on restores the remembered count, or `null` for the default) with the remembered counts held in `Settings` so they survive a tab switch. Verify with tests: count shown greyed rather than 0 while off, restored on re-enable, default 6 when none remembered, and nothing sent until Save.
- [x] 2.4 Refuse the off value while the switch is on, with a message pointing at the switch, and raise the number input's `min` to 1 while on (design D5). Verify with tests: typing 0 shows the error and sends no request; turning off then Save sends `{g_maplist_votable: 0}` and reports "next map".
- [x] 2.5 Run `npm --prefix web test` and `npm --prefix web run build`; verify both pass.

## 3. Integration

- [x] 3.1 Run the full Python suite (`.venv/bin/python -m pytest`) and lint; verify it passes.
- [x] 3.2 In the running panel (dev server against the fake Xonotic server), open Settings → Voting and verify the switch greys the fields, Save with it off writes `g_maplist_votable 0`, and a reload with it off then on offers 6.

## Workflow follow-up

- Archive the change once reviewed, syncing the `server-settings` delta into the main spec.
