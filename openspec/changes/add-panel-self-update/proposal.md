# Proposal

## Why

The panel cannot tell the operator that it is out of date, and the only way to upgrade it
is to open a root shell on the host and re-run the installer. Cobble, the sibling Bedrock
panel, already solves this with a header version badge, a page with one-click upgrade and
a root helper that does the privileged work. This change brings the same behaviour to
xonotic-webui while the install base is small, so that only today's v0.1.x installs need
one last manual upgrade.

## What Changes

- **Release check.** The panel checks the project's GitHub releases shortly after start
  and then periodically. It keeps one cached result for every browser and survives being
  offline. Drafts and pre-releases are never offered.
- **Header version badge.** The running panel version appears in square brackets beside
  the brand: green when current, orange `[<version> update available]` when a newer
  release exists, and neutral when availability is unknown. Activating it opens the panel
  page.
- **Panel page** (`/panel`, not in the navigation bar). It shows the installed and latest
  versions, update status, last check time, a "Check now" action, a link to the release
  on GitHub, the latest release's notes rendered safely from Markdown, and the outcome of
  the last upgrade. When an update is available it offers either a confirmed one-click
  upgrade or, on installs without the helper, the root command to copy.
- **One-click upgrade through a root helper.** The unprivileged panel only *requests* an
  upgrade, naming the exact release it reported. A root-owned helper, started by a systemd
  path unit, accepts only a version tag and a request id. It downloads that release from
  the repository fixed at install time, verifies the published sha256 digests, and runs
  that release's installer, which restarts the panel and rolls back if the new panel does
  not come up. The panel reports the outcome after it restarts. While an upgrade is in
  flight the interface shows a banner and reloads itself onto the new version.
- **Game downtime limited to the panel restart.** Unlike Cobble, there is no pre-upgrade
  backup and the game server is not stopped before the hand-off. It goes down when the
  installer restarts the panel and comes back on its own if it was running, because the
  panel already persists its running intent.
- **Installer** installs and enables the helper and its units, and creates the request and
  status directories with the ownership the trust boundary needs.
- **Release notes from a changelog.** A `CHANGELOG.md` gets one section per released
  version. The release workflow publishes that section as the release notes and refuses
  to publish a tag without one. This replaces GitHub's generated notes.

Out of scope: upgrading or changing the pinned Xonotic game release from the interface;
pre-release or channel selection; automatic (unattended) upgrades; downgrades;
authentication.

## Capabilities

### New Capabilities

- `panel-self-update`: keeping the panel itself current. Covers reporting the running
  version; the periodic, cached and offline-tolerant release check; whether one-click
  upgrade is possible; requesting an upgrade to the reported release; the privileged
  helper and its trust boundary; preserving the game server's running intent across the
  upgrade; recording and reporting the outcome; and release notes sourced from the
  changelog.

### Modified Capabilities

- `web-ui-shell`: adds the header version badge with its update state, the panel page with
  its upgrade controls and release notes, and the in-flight upgrade banner with automatic
  reload.
- `installation`: the installer also installs and enables the root upgrade helper, and the
  service user can request an upgrade but cannot alter the helper, its units or its status.

## Impact

- **Backend**: new `xonotic_webui/selfupdate/` package (version parsing, release check,
  upgrade request and follow-up); new `/api/panel/version`, `/api/panel/check` and
  `/api/panel/upgrade` routes; new settings for the release repository, check interval,
  enable switch and upgrade timeout; `httpx` moves from a dev dependency to a runtime
  dependency.
- **Frontend**: version badge and upgrade banner in the shell, a `/panel` route registered
  with `nav: false`, a version context polled by the shell, and `react-markdown` for the
  release notes. Generated API types and the OpenAPI snapshot are regenerated.
- **Deploy**: new `deploy/xonotic-webui-upgrade` (stdlib Python, run by the system
  `python3`) and `xonotic-webui-upgrade.path` and `.service` units; changes to
  `deploy/install.sh`.
- **Release process**: new `CHANGELOG.md` and `.github/scripts/release-notes.sh`;
  `release.yml` publishes the changelog section, and the manual dry run validates it too.
  Each version bump must add a changelog entry.
- **Existing installs**: v0.1.0 and v0.1.1 have no helper. Their first upgrade to the
  release that ships this is the manual root command, which the panel page shows. After
  that, upgrades can be done from the page.
- **Security**: the request file is written by the service user and read by root. It is
  treated as untrusted input: no symlinks, a size limit, and only a well-formed tag and
  request id are accepted. The repository and the download source are never taken from
  it.
