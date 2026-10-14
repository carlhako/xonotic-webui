# Design

## Context

See `proposal.md` for motivation and scope. The requirements are in
`specs/panel-self-update`, `specs/web-ui-shell` and `specs/installation`.

This is a port of Cobble's self-update (`~/projects/bedrock-server`: `cobble/selfupdate/`,
`deploy/cobble-upgrade*`, `web/src/sections/Cobble.tsx`, `web/src/api/useCobbleVersion.tsx`,
`.github/scripts/release-notes.sh`). That code has been run in production. This design
records only where xonotic-webui differs, and why.

The relevant pieces of xonotic-webui as built:

- **Version.** `__version__` lives in `xonotic_webui/__init__.py`, and `/health` already
  returns `{"status": "ok", "version": ...}`.
- **Install layout.** `deploy/install.sh` installs the application root-owned under
  `/opt/xonotic-webui`, with state under `/var/lib/xonotic-webui` owned by the service
  user. It can install from a local tarball (`XONOTIC_WEBUI_TARBALL`) and pin a release
  (`RELEASE_TAG`). It builds the new venv *before* stopping the service, swaps it in,
  waits for `/health` to report the new version, and restores the previous venv and unit
  if that fails. Name-bearing values derive from `APP_NAME` (B-D16).
- **Running intent.** The supervisor persists `desired_running` and clears it only on an
  operator stop. A panel shutdown (`aclose`) quits the game but keeps the intent, and
  `restore()` brings the game back on the next start.
- **Service sandbox.** The unit runs with `ProtectSystem=strict` and
  `ReadWritePaths=/var/lib/xonotic-webui`. The panel can read the rest of `/var` but can
  write only its state directory.
- **No maintenance scope or backups.** Cobble's upgrade leans on both. There is only the
  supervisor's lifecycle `_op_lock` and its `STARTING`/`STOPPING` states.
- **Typed API.** Routes declare pydantic response models in `api/schemas.py`. An OpenAPI
  snapshot test and the generated `web/src/api/schema.d.ts` (checked in CI) must be
  regenerated when routes change.
- **Section registry.** `web/src/sections.tsx` already supports `nav: false`.

## Goals / Non-Goals

**Goals:**

- Behaviour and trust boundary equivalent to Cobble's, so both projects can be reasoned
  about and maintained the same way.
- Game downtime during an upgrade no longer than an ordinary panel restart.
- The helper and the panel each test in isolation, without root and without GitHub.

**Non-Goals:**

- A shared library between Cobble and xonotic-webui. The code is copied and adapted. The
  projects release independently and the shared surface is small.
- Holding off lifecycle actions while an upgrade is pending (see D4).

## Decisions

### D1. Port Cobble's modules with names derived from `APP_NAME`

New package `xonotic_webui/selfupdate/` with three modules:

- `version.py`, copied verbatim.
- `release_check.py`, with the same `ReleaseChecker`: GitHub `releases/latest`, ETag
  conditional requests, a state file with a `schema` number, `check()` shared under a
  lock, and a loop that waits 30 s after start and then runs every interval.
- `upgrade.py`, a reduced `UpgradeService` (see D3).

The helper is `deploy/xonotic-webui-upgrade` with units
`xonotic-webui-upgrade.path` and `xonotic-webui-upgrade.service`. Paths:

| What | Path | Owner |
|---|---|---|
| helper | `/usr/local/libexec/xonotic-webui/xonotic-webui-upgrade` | root, 0755 |
| request | `/var/lib/xonotic-webui/upgrade/request.json` | service user |
| helper status | `/var/lib/xonotic-webui-upgrade/status.json` | root, dir 0755 |
| release check cache | `/var/lib/xonotic-webui/release_check.json` | service user |
| pending / last outcome | `/var/lib/xonotic-webui/upgrade_pending.json`, `upgrade_last.json` | service user |

The status directory sits outside the state directory. The service user owns the state
directory and could otherwise replace a root-written file there.

New settings, with the `XONOTIC_WEBUI_` prefix:

| Setting | Default | Notes |
|---|---|---|
| `release_repo` | `carlhako/xonotic-webui` | |
| `release_api_url` | `https://api.github.com` | |
| `release_check_enabled` | `true` | |
| `release_check_interval_hours` | `12` | |
| `upgrade_helper_path` | the helper path above | |
| `upgrade_status_dir` | the status directory above | |
| `upgrade_timeout_seconds` | `3900` | see D5 |
| `user_agent` | `xonotic-webui/<version> (+https://github.com/<release_repo>)` | |

Derived property: `upgrade_request_dir = state_dir / "upgrade"`.

*Alternative considered:* a generic name such as `selfupdate-helper`. Rejected because
`APP_NAME`-derived names keep the "rename in one place" rule (B-D16).

### D2. `httpx` becomes a runtime dependency

The release check uses `httpx` with an injectable transport, as in Cobble, so Cobble's
tests port with little change (`httpx.MockTransport`). It is already in the dev extras,
and the wheel is pure Python. The helper stays stdlib-only (`urllib`), because the system
`python3` runs it, never the venv it is replacing.

*Alternative considered:* `urllib` in the panel too. Rejected because it means rewriting
the check's tests for no runtime benefit.

### D3. No backup and no pre-emptive stop: the hand-off is just two files

Cobble's request path is: take the maintenance scope, stop the server, take a verified
backup, re-arm the running intent, write the request, then wait while holding
maintenance. None of that applies here:

- There is no backup feature, and the installer never touches configuration or state.
- The installer already keeps the old panel serving while it downloads, verifies and
  builds. It stops the service only to swap the venv, and the panel's own shutdown quits
  the game cleanly while keeping `desired_running`.

So `UpgradeService.request(version)` validates the request (D4), then atomically writes
two files:

- `upgrade_pending.json`, with `{from, to, tag, request_id, requested_at}`
- `upgrade/request.json`, with `{tag, request_id}`

It then starts a background follow task and returns the view (`pending`). The follow task
is Cobble's `_await_helper` and `_follow` merged into one poll loop. It runs in two
cases:

- **Right after a request.** If the old panel sees a terminal status for this
  `request_id`, the helper failed or rejected the request without restarting the panel.
  The task records it in `upgrade_last.json`, clears `pending`, and removes any leftover
  request file. `succeeded` without a restart is recorded as a failure, as in Cobble.
- **On startup, when `upgrade_pending.json` exists.** This is the restarted (new or
  rolled-back) panel. The task keeps polling until the status is terminal, allowing a
  grace period while the helper still reports `running`, because the installer restarts
  the panel before the helper writes its final status. It then concludes:
  - **succeeded**, if the status says so and `to == __version__`;
  - **failed**, otherwise, with the helper's `log_tail` (this covers the installer's
    rollback);
  - **failed ("interrupted")**, if the deadline passes with no terminal status.

Outcomes are matched by `request_id`. A status with no id counts only if it is a
`rejected` status that finished after the request was made, exactly as in Cobble.

### D4. Refusals and lifecycle interplay

`request()` raises `UpgradeError(code, message)`, mapped to 409 `{code, message}` through
the existing `api_error` helper. Codes are checked in this order:

1. `upgrade_in_progress`: a follow task is running or `upgrade_pending.json` exists.
2. `helper_not_installed`: the helper file or the status directory is missing.
3. `no_update_available`
4. `version_mismatch`
5. `transition_in_progress`: the supervisor state is `STARTING` or `STOPPING`, or
   `_op_lock` is held. This reuses the condition the lifecycle routes already check,
   exposed as a small public predicate on the supervisor.

Lifecycle actions are **not** blocked while an upgrade is pending. Stopping the game
mid-download is harmless: it clears the intent, and the upgraded panel leaves the game
stopped, as the spec requires. Blocking would need a maintenance concept this project
does not have, for no safety gain.

### D5. Timeouts sized for a possible game download

A release that changes `XONOTIC_VERSION` makes the installer download about 1.24 GB of
game data inside the helper's run, while the old panel keeps serving. The timeouts are:

- Helper unit `TimeoutStartSec=60min`.
- Panel `upgrade_timeout_seconds=3900` (65 min), which must exceed the unit's timeout.
  The setting's description says so, as Cobble's does.
- Helper `MAX_ASSET_BYTES` is 256 MiB. That limits only the panel tarball and
  `install.sh`; the game archive is fetched and verified against its pinned digest by
  the installer, not the helper.

### D6. The helper: Cobble's, with the asset names and installer variables swapped

The trust boundary is unchanged. The helper:

- takes the request by renaming `request.json` to `request.processing` (so the path unit
  does not retrigger);
- reads it with `O_NOFOLLOW`, requires a small regular file, and refuses a request
  directory that is a symlink or not owned by the service user;
- accepts only `^v\d{1,4}\.\d{1,4}\.\d{1,4}$` and `^[0-9a-f]{32}$`;
- looks the tag up in `REPO`, which the installer bakes in with `sed` (an `owner/name`
  regex guards the value);
- downloads `install.sh` and `xonotic-webui.tar.gz` into a 0700 root temp directory;
- verifies each against the asset's `digest` (`sha256:...`) from the releases API, and
  fails closed if one is missing;
- runs `bash install.sh` with a clean environment:
  `XONOTIC_WEBUI_TARBALL=<downloaded>`, `RELEASE_TAG=<tag>`, `XONOTIC_WEBUI_REPO=<REPO>`;
- writes `status.json` (`running`, then `succeeded`, `failed` or `rejected`) with the
  `request_id`, the exit code and an ANSI-stripped 200-line tail of the output.

Test-only environment overrides for the request directory, status directory and API URL
are kept, as in Cobble. Only root can edit the unit, so they cannot be abused.

GitHub has published `digest` on release assets since 2025. The v0.1.1 release already
carries one for both assets.

### D7. The panel's release repository follows the installer's

Cobble's panel always checks its default repository, even when the installer was pointed
at another. xonotic-webui keeps the two in step instead. When `REPO` differs from
`GITHUB_REPO`, the installer writes a root-owned systemd drop-in,
`/etc/systemd/system/xonotic-webui.service.d/release-repo.conf`, setting
`Environment=XONOTIC_WEBUI_RELEASE_REPO=<REPO>`. When `REPO` is the default, it removes
the drop-in. The helper and the check can then never disagree about which repository
"latest" comes from.

*Alternative considered:* writing the value into the seeded env file. Rejected because
that file is seeded once and is the operator's to edit, so a re-run could not keep it in
step.

### D8. API

All routes are under `/api/panel`, with response model `PanelVersion`:

- `GET /version`
- `POST /check`
- `POST /upgrade` with body `{"version": "x.y.z"}`, returning 409 `{code, message}` on
  refusal

`PanelVersion` holds:

- the check: `current`, `latest`, `update_available`, `release_url`, `release_name`,
  `published_at`, `notes`, `checked_at`, `check_error`;
- `one_click_available`, and `manual_command`, which is null when one-click is available;
- `upgrade`: null, or `{state, from, to, requested_at, finished_at, error, log_tail}`,
  where `state` is `pending`, `running`, `succeeded`, `failed` or `rejected`.

The manual command is
`curl -fsSL https://github.com/<release_repo>/releases/latest/download/install.sh | bash`.
The README's install section uses the same command.

### D9. Frontend

- **`api/usePanelVersion.tsx`**: `PanelVersionProvider` and `usePanelVersion()`, ported
  from `useCobbleVersion`. It polls `/api/panel/version` every 5 min, and every 3 s while
  an upgrade is in flight. While in flight it watches `/health`, and reloads when the
  version differs from the one the page loaded with.
- **Header** (`App.tsx`): `VersionBadge` beside the brand (`.version-badge`, `.is-current`
  in the accent colour, `.is-update` in the warn colour, mono font), and `UpgradeBanner`
  under the header.
- **`sections/Panel.tsx`**: registered as `{ path: "/panel", label: "Panel", nav: false }`.
  It is Cobble's `CobbleCard` and `ReleaseNotes`, without the settings card. The
  confirmation uses the existing `components/Confirm.tsx` and states that the game server
  will restart and players will be disconnected. The upgrade action is disabled when
  disconnected, during a lifecycle transition, or while an upgrade is in flight.
- **Release notes**: `react-markdown` without `rehype-raw`, with the default
  `urlTransform`, and links opening in a new tab with `rel="noopener noreferrer"`.
- **No header cog.** In Cobble the cog also reaches the timezone settings. Here the
  only panel-level content is the version, so the badge is the single entry point.

### D10. Changelog and release workflow

- **`CHANGELOG.md`**: a short header stating the rule, then `## <version> - <date>`
  sections, newest first. It is backfilled with entries for 0.1.0 and 0.1.1; the
  already-published release bodies are not edited.
- **`.github/scripts/release-notes.sh`**: copied from Cobble with only the help text
  changed.
- **`release.yml`**:
  - The first step runs `release-notes.sh "$GITHUB_REF_NAME"` on a tag. On
    `workflow_dispatch` it uses the version from `pyproject.toml`, so the dry run catches
    a missing entry.
  - The publish step uses `body_path: release-notes.md` and drops
    `generate_release_notes`.
- **`tests/test_release.py`**: gains tests for the script (missing, empty and present
  sections, and a version that is a prefix of another, such as `0.1.1` vs `0.1.10`), and
  a test that `CHANGELOG.md` has a section for the version in `pyproject.toml`.

## Risks / Trade-offs

- **[Risk] Root reads a file the service user writes.**
  → The helper's input handling is copied unchanged from Cobble (no symlinks, size cap,
  strict regexes, repository fixed at install). Its tests include the hostile cases:
  symlinked request, symlinked directory, oversized file, bad tag, bad id.
- **[Risk] A future release breaks the installer, and every one-click upgrade fails.**
  → The installer's existing rollback restores the previous panel. The outcome and log
  tail show on the panel page. The manual command remains a fallback.
- **[Risk] GitHub stops publishing asset digests or changes their format.**
  → The helper fails closed with a clear error, and the manual command still works.
- **[Trade-off] No backup before upgrading.**
  → Acceptable because the installer never writes configuration or state. If a
  backup feature is added later, it can hook into `request()` before the hand-off.
- **[Risk] Unauthenticated GitHub API rate limit (60 per hour per IP) on hosts behind
  shared NAT.**
  → One check per 12 h plus manual checks, and ETag revalidations returning 304 do not
  count. A refusal is reported as `check_error` and the last result is kept.
- **[Trade-off] The upgrade path is only exercised for real on a host.**
  → Unit tests cover the panel and the helper separately, using a fake release server
  and a stub installer. The end-to-end check is manual, on the test LXC (tasks).

## Migration Plan

1. Release vN (the first version with this change) with a `CHANGELOG.md` entry.
2. Existing v0.1.x installs show nothing new until they are upgraded once by hand:
   `curl ... | bash` as root. That run installs the helper.
3. From vN on, the panel shows the badge and offers one-click upgrade to vN+1.
4. Rollback of a bad release is the same as today: re-run the installer with
   `RELEASE_TAG=<previous>`. Downgrades are not offered in the interface.
