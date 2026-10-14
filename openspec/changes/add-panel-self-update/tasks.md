# Tasks

Run the groups in order; each depends on the ones before it. Design decisions are cited
as D1–D10 (`design.md`). "Cobble" means `~/projects/bedrock-server`, the source of the
ported code (`src/cobble/selfupdate/`, `deploy/cobble-upgrade*`,
`tests/selfupdate/`, `web/src/sections/Cobble.tsx`, `web/src/api/useCobbleVersion.tsx`,
`.github/scripts/release-notes.sh`).

## 1. Dependencies and settings

- [x] 1.1 Move `httpx` from the dev extras to the runtime dependencies in `pyproject.toml` (D2); verify `pip install -e '.[dev]'` succeeds and the wheel's metadata lists `httpx`
- [x] 1.2 Add the self-update settings to `settings.py` (`release_repo`, `release_api_url`, `release_check_enabled`, `release_check_interval_hours`, `upgrade_helper_path`, `upgrade_status_dir`, `upgrade_timeout_seconds` with its description tying it to the helper unit's timeout, `user_agent`, and the `upgrade_request_dir` property), with defaults derived from `APP_NAME` (D1, D5); verify tests in `tests/test_settings.py` for the defaults, environment overrides and that `upgrade_timeout_seconds` exceeds the helper unit's `TimeoutStartSec`

## 2. Release check (panel-self-update)

- [x] 2.1 Port `version.py` into `xonotic_webui/selfupdate/` with its tests; verify `tests/selfupdate/test_version.py` passes, including `v`-prefixed tags, non-version tags and a running version newer than the latest
- [x] 2.2 Port `ReleaseChecker` into `selfupdate/release_check.py` (D1): conditional requests with ETag, drafts and pre-releases rejected, empty notes reported as absent, the persisted `release_check.json` with a `schema` number, a failed check keeping the last result and recording `check_error`, the user agent, a lock-shared `check()`, and a start loop that waits 30 s and honours `release_check_enabled`; verify `tests/selfupdate/test_release_check.py` (ported, using `httpx.MockTransport`) covers newer, same, older, pre-release, non-version tag, 304, 403/429, 404, unreachable, empty notes, an older schema forcing a full fetch, restart while offline, and disabled checks
- [x] 2.3 Wire the checker into `Runtime` (created with the settings, started in `startup()` without delaying `restore()`, stopped in `shutdown()`); verify a runtime wiring test that startup does not wait for the check and shutdown cancels the loop

## 3. Upgrade request and outcome (panel-self-update)

- [x] 3.1 Add a public `transition_in_progress()` predicate to the supervisor (state `STARTING`/`STOPPING` or `_op_lock` held) and use it in the existing lifecycle guards (D4); verify the existing supervisor tests still pass and new tests cover the predicate in each state
- [x] 3.2 Implement `UpgradeService.request(version)` in `selfupdate/upgrade.py` (D3, D4): the refusals in order (`upgrade_in_progress`, `helper_not_installed`, `no_update_available`, `version_mismatch`, `transition_in_progress`) as `UpgradeError(code, …)`, then atomically write `upgrade_pending.json` and `upgrade/request.json` with a fresh 32-hex `request_id`, and start the follow task; verify tests for each refusal (and that it writes nothing), the two files' contents, and that the game server is not stopped by a request
- [x] 3.3 Implement the follow task and the outcome record (D3): match the helper's `status.json` by `request_id` (a `rejected` status with no id counts only if it finished after the request); conclude `succeeded` only when `to` equals the running version; record `failed`/`rejected` with `log_tail`; give up with "interrupted" after `upgrade_timeout_seconds`, with the grace period while the helper still reports `running`; clear `pending` and any leftover request file; verify ported `tests/selfupdate/test_upgrade.py` cases: success after restart, failure before restart, installer rollback (old version running, status failed), malformed request rejected, retry after a failed attempt at the same tag, slow install past the timeout, and a stale status from an earlier request ignored
- [x] 3.4 Implement `view()` and `manual_command()` (D8) and start the follow task from `Runtime.startup()` when `upgrade_pending.json` exists; verify tests that a pending upgrade reports `pending` then `running` once the helper's status names its id, and that a restarted panel with a pending record concludes it

## 4. Panel version API

- [x] 4.1 Add `PanelVersion` and `PanelUpgrade` models to `api/schemas.py` and an `api/panel.py` router with `GET /api/panel/version`, `POST /api/panel/check` and `POST /api/panel/upgrade` (`{"version": …}`; 409 `{code, message}` via `api_error` on refusal) (D8); register it in `api/__init__.py`; verify API tests for each route, each refusal code, `manual_command` present only without the helper, and an unknown `/api/panel/...` path returning an error rather than the application page
- [x] 4.2 Regenerate `web/openapi.json` and `web/src/api/schema.d.ts`; verify `tests/test_openapi_snapshot.py` passes and `npm --prefix web run build` type-checks

## 5. Root upgrade helper

- [x] 5.1 Port Cobble's helper as `deploy/xonotic-webui-upgrade` (D6): `REPO = "carlhako/xonotic-webui"` as the line the installer rewrites, request taken by rename with `O_NOFOLLOW`, size cap and regular-file check, request directory refused if it is a symlink or not owned by the service user, strict tag and id regexes, release lookup by tag in `REPO`, downloads of `install.sh` and `xonotic-webui.tar.gz` into a 0700 temp directory verified against the asset `digest` (fail closed if missing), installer run with a clean environment (`XONOTIC_WEBUI_TARBALL`, `RELEASE_TAG`, `XONOTIC_WEBUI_REPO`), and `status.json` written with `request_id`, state, exit code and an ANSI-stripped 200-line tail; verify ported helper tests running it unprivileged against a local fake release server and a stub installer: success, malformed tag, malformed id, symlinked request, symlinked request directory, oversized request, digest mismatch, missing digest, installer non-zero exit
- [x] 5.2 Add `deploy/xonotic-webui-upgrade.path` (`PathExists=/var/lib/xonotic-webui/upgrade/request.json`) and `deploy/xonotic-webui-upgrade.service` (oneshot, root, system `/usr/bin/python3`, `TimeoutStartSec=60min`, no dependency on the panel unit) (D5); verify `systemd-analyze verify` in CI passes for the new units and a test asserts their paths match the helper's and the settings' defaults
- [x] 5.3 Run the helper under the CI checks: add it to `ruff check`/`ruff format --check` paths and extend `.github/workflows/ci.yml` to verify `deploy/*.path`; verify CI's lint and installer jobs pass locally with the same commands

## 6. Installer (installation)

- [x] 6.1 Install the helper and its units from the release tarball: helper root 0755 at `/usr/local/libexec/xonotic-webui/` with `REPO` baked in by `sed` after an `owner/name` check, the request directory `STATE_DIR/upgrade` owned by the service user, the status directory `/var/lib/xonotic-webui-upgrade` root 0755, and `systemctl enable --now xonotic-webui-upgrade.path`, all `APP_NAME`-derived and `DESTDIR`-aware; verify `tests/test_installer.py` sandbox cases for a fresh install, a re-run over an install without the helper, and the baked `REPO` for a custom `XONOTIC_WEBUI_REPO`
- [x] 6.2 Extend `repair_ownership` and `verify_layout` to the helper, its units and the status directory (root-owned, not writable by the service user) and to the request directory (writable by the service user); verify the user-namespace layout test asserts the service user can write the request directory, read but not write the status directory, and cannot modify the helper
- [x] 6.3 Write or remove the `xonotic-webui.service.d/release-repo.conf` drop-in according to whether `REPO` differs from `GITHUB_REPO` (D7); verify installer tests for the default (no drop-in, and a stale one removed) and a custom repo (drop-in sets `XONOTIC_WEBUI_RELEASE_REPO`)
- [x] 6.4 Update the README: an "Upgrading" section (the header badge, the panel page, one-click upgrade, the one-time manual upgrade for v0.1.x installs, rollback by `RELEASE_TAG`), the release-check settings, and the helper, units and new state files in "Where things live"; verify `tests/test_readme.py` passes and every path and setting named matches the code's constants

## 7. Shell: version badge and upgrade banner (web-ui-shell)

- [x] 7.1 Add `react-markdown` to the web dependencies and the `panelVersion`, `panelCheck` and `panelUpgrade` calls to `api/client.ts`; verify `npm --prefix web run build` succeeds
- [x] 7.2 Port `useCobbleVersion` as `api/usePanelVersion.tsx` (D9): provider plus hook, 5 min poll, 3 s poll while an upgrade is in flight, a `/health` watch that reloads when the version changes and ignores connection errors; verify vitest cases with fake timers for the poll intervals, reload on a new version, no reload on the same version, and a failed outcome picked up without a reload
- [x] 7.3 Add `VersionBadge` beside the brand and `UpgradeBanner` under the header in `App.tsx`, with `.version-badge`, `.is-current` and `.is-update` styles in `styles.css` (D9); verify `shell.test.tsx` cases for `[x.y.z]` green, `[x.y.z update available]` orange, unknown availability with no claim, the badge linking to `/panel`, the badge updating without a reload, the banner naming the target version, and no horizontal overflow at 375px

## 8. Panel page (web-ui-shell)

- [x] 8.1 Add `sections/Panel.tsx` and register `{ path: "/panel", label: "Panel", nav: false }` (D9): installed, latest and status cards, last-checked time in the browser's timezone, the check error, the "View on GitHub" link, "Check now", and the last upgrade's outcome with the log tail on failure; verify `panel.test.tsx` cases for up to date, update available, never checked, check failed, last upgrade succeeded and failed, the route not appearing in the navigation, and a deep link to `/panel` rendering the page
- [x] 8.2 Add the upgrade action with `components/Confirm.tsx` stating that the game server will restart and players will be disconnected, the manual command with a copy action when one-click is unavailable, refusal reasons shown, and the action disabled while disconnected, during a lifecycle transition, or while an upgrade is in flight; verify vitest cases for each of those states and that the upgrade call is made only on confirmation
- [x] 8.3 Add the release notes panel with `react-markdown` (no `rehype-raw`, default `urlTransform`, links with `target="_blank" rel="noopener noreferrer"`), the version and publish date, a title only when it says more than the version, and "No release notes were published" for empty notes; verify vitest cases that `<script>` and `<img onerror>` in notes are not rendered as HTML, links open externally, and empty notes show the message with the GitHub link

## 9. Changelog and release workflow (panel-self-update)

- [x] 9.1 Copy `release-notes.sh` to `.github/scripts/` (D10) and add `CHANGELOG.md` with its header and backfilled 0.1.0 and 0.1.1 sections; verify tests in `tests/test_release.py` for a present section, a missing section, an empty section, `v`-prefixed input, a `0.1.1` vs `0.1.10` prefix, and that the version in `pyproject.toml` has a section
- [ ] 9.2 Update `release.yml`: a first step producing `release-notes.md` from the tag, or from the `pyproject.toml` version on `workflow_dispatch`, and the publish step using `body_path` instead of `generate_release_notes`; add `shellcheck` of the script to the CI installer job; verify `shellcheck` passes, and a manual workflow dry run on the branch succeeds and its log shows the notes step
- [x] 9.3 Bump the version to 0.2.0 in `pyproject.toml` and `__init__.py` with a `## 0.2.0 - <date>` changelog entry describing the badge, the panel page and one-click upgrades, including the one-time manual upgrade for v0.1.x; verify `pytest -q`, `npm --prefix web test` and the changelog test pass

## 10. End-to-end on a real host

- [ ] 10.1 On the test LXC (10.0.1.147), running v0.1.1 with the game server running and a player-free server: publish v0.2.0, confirm the v0.1.1 panel shows nothing new, run the manual root command, and verify the 0.2.0 panel comes up with the game server running again, the helper and units installed with the ownership in the spec, and the badge showing `[0.2.0]` in green
- [ ] 10.2 Publish a v0.2.1 patch release with a changelog entry, then on the LXC: verify the badge turns orange after "Check now", the panel page shows 0.2.1's notes, a confirmed upgrade shows the banner, the game server keeps running until the panel restarts, the page reloads onto 0.2.1, the badge is green, the game server is running, and the panel page reports the upgrade 0.2.0 → 0.2.1 as succeeded
- [ ] 10.3 On the LXC, with the game server stopped from the dashboard, write `upgrade_pending.json` and `upgrade/request.json` as the service user naming v0.2.1, the version already installed, so the helper reinstalls it; verify the panel restarts, the game server stays stopped, and the outcome is reported as succeeded
- [ ] 10.4 On the LXC, write `upgrade_pending.json` and `upgrade/request.json` as the service user naming a non-existent tag (`v9.9.9`), then `systemctl restart xonotic-webui` so the startup follow task picks the request up (requests placed by hand are not followed by a running panel); verify the helper records a failure without touching the install, the panel page shows the failure with its output, the banner clears, and the game server's running intent is unchanged

## Workflow follow-up

- Publishing v0.2.0 and v0.2.1 (10.1, 10.2) pushes tags and creates public GitHub releases; confirm each with the user before pushing.
- Archive the change with `/opsx:archive` once group 10 has passed, syncing the `panel-self-update`, `web-ui-shell` and `installation` specs.
