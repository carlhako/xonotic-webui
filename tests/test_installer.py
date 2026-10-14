"""The installer's steps, exercised without root in a scratch tree (DESTDIR) with
PATH shims standing in for system commands."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "deploy" / "install.sh"
UNIT = ROOT / "deploy" / "xonotic-webui.service"

if sys.platform != "linux":  # pragma: no cover
    pytest.skip("linux-only deploy assets", allow_module_level=True)

PINNED = "50850f8d800e7499722f6ea61e478e96464a375494b5a24da93aa0598cbe964d"


class Sandbox:
    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "dest"
        self.root.mkdir()
        self.shims = tmp_path / "shims"
        self.shims.mkdir()
        self.calls = tmp_path / "calls.log"
        self.calls.write_text("")
        self.tmp = tmp_path

    def shim(self, name: str, body: str) -> None:
        path = self.shims / name
        path.write_text(f'#!/bin/bash\necho "{name} $*" >> "{self.calls}"\n{body}\n')
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def called(self, name: str) -> list[str]:
        return [line for line in self.calls.read_text().splitlines() if line.split(" ")[0] == name]

    def env(self, **extra: str) -> dict[str, str]:
        base = {
            **os.environ,
            "DESTDIR": str(self.root),
            "PATH": f"{self.shims}:{os.environ['PATH']}",
            "OS_RELEASE_FILE": str(self.tmp / "os-release"),
        }
        base.update(extra)
        return base

    def tree(self) -> list[str]:
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))

    def run_script(self, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(INSTALL)],
            env=env or self.env(),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def call(self, snippet: str, **extra: str) -> subprocess.CompletedProcess[str]:
        """Source the installer (without running it) and run ``snippet``."""
        script = f'set -euo pipefail\nsource "{INSTALL}"\n{snippet}\n'
        return subprocess.run(
            ["bash", "-c", script],
            env=self.env(**extra),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )


@pytest.fixture
def sb(tmp_path: Path) -> Sandbox:
    (tmp_path / "os-release").write_text('ID=debian\nVERSION_ID="13"\n')
    return Sandbox(tmp_path)


def make_game_zip(path: Path, *, with_music: bool = True) -> str:
    """A tiny archive with the real layout; returns its SHA-256."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Xonotic/xonotic-linux64-dedicated", "#!/bin/sh\nexit 0\n")
        z.writestr("Xonotic/key_0.d0pk", "key")
        z.writestr("Xonotic/data/xonotic-test-data.pk3", "data")
        z.writestr("Xonotic/data/xonotic-test-maps.pk3", "maps")
        z.writestr("Xonotic/xonotic.exe", "client we do not need")
        z.writestr("Xonotic/source/big.c", "source we do not need")
        if with_music:
            z.writestr("Xonotic/data/xonotic-test-music.pk3", "music")
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- 9.2 preflight -------------------------------------------------------------------


def test_script_is_syntactically_valid_and_pins_the_game() -> None:
    assert subprocess.run(["bash", "-n", str(INSTALL)], check=False).returncode == 0
    text = INSTALL.read_text()
    assert PINNED in text
    assert "--only-binary=:all:" in text


@pytest.mark.skipif(os.geteuid() == 0, reason="needs a non-root user")
def test_non_root_is_refused_and_nothing_changes(sb: Sandbox) -> None:
    r = sb.run_script()
    assert r.returncode != 0
    assert "must be run as root" in r.stderr
    assert sb.tree() == []
    assert sb.called("apt-get") == []


def test_unsupported_architecture_names_both_and_changes_nothing(sb: Sandbox) -> None:
    sb.shim("id", "echo 0")
    sb.shim("uname", "echo aarch64")
    sb.shim("apt-get", "exit 0")
    r = sb.run_script()
    assert r.returncode != 0
    assert "aarch64" in r.stderr
    assert "x86_64" in r.stderr
    assert sb.tree() == []
    assert sb.called("apt-get") == []


def test_non_debian_family_is_refused(sb: Sandbox) -> None:
    (sb.tmp / "os-release").write_text("ID=fedora\n")
    sb.shim("id", "echo 0")
    sb.shim("uname", "echo x86_64")
    sb.shim("apt-get", "exit 0")
    r = sb.run_script()
    assert r.returncode != 0
    assert "Debian-family" in r.stderr
    assert sb.tree() == []


def test_debian_derivative_is_accepted_by_the_platform_check(sb: Sandbox) -> None:
    (sb.tmp / "os-release").write_text("ID=ubuntu\nID_LIKE=debian\n")
    sb.shim("uname", "echo x86_64")
    sb.shim("apt-get", "exit 0")
    assert sb.call("require_platform").returncode == 0


def test_insufficient_disk_space_states_required_and_available(sb: Sandbox) -> None:
    sb.shim("id", "echo 0")
    sb.shim("uname", "echo x86_64")
    sb.shim("apt-get", "exit 0")
    # 100 MiB free
    sb.shim(
        "df",
        'printf "Filesystem 1-blocks Used Available Use%% Mounted\\nfs 1 1 104857600 1%% /\\n"',
    )
    r = sb.run_script()
    assert r.returncode != 0
    assert "3072 MiB" in r.stderr  # required
    assert "100 MiB" in r.stderr  # available
    assert sb.tree() == []
    assert sb.called("apt-get") == []


def test_space_check_is_skipped_once_the_game_is_installed(sb: Sandbox) -> None:
    sb.shim("df", 'printf "h\\nfs 1 1 1 1%% /\\n"')  # 1 byte free
    r = sb.call(
        'mkdir -p "$GAME_DIR/data"; touch "$GAME_DIR/xonotic-linux64-dedicated"; '
        'chmod +x "$GAME_DIR/xonotic-linux64-dedicated"; require_space'
    )
    assert r.returncode == 0, r.stderr


# --- 9.3 users, layout --------------------------------------------------------------------


def test_layout_has_root_owned_application_and_game_trees(sb: Sandbox) -> None:
    # `install -o <user>` needs the user to exist; shim it so the layout is exercised.
    sb.shim(
        "install",
        'args=("$@"); mode=; dirs=0\nfor a in "$@"; do [ "$a" = -d ] && dirs=1; done\n'
        'for a in "$@"; do case "$a" in -*|root|xonotic-webui|0755) ;; '
        '*) mkdir -p "$a";; esac; done',
    )
    r = sb.call("ensure_dirs")
    assert r.returncode == 0, r.stderr
    for rel in [
        "opt/xonotic-webui",
        "opt/xonotic",
        "var/lib/xonotic-webui/userdir/data",
        "etc/xonotic-webui",
    ]:
        assert (sb.root / rel).is_dir(), rel
    owners = " ".join(sb.called("install"))
    # application and game parents are root's; only state belongs to the service user
    assert "-o root -g root" in owners
    assert "-o xonotic-webui -g xonotic-webui" in owners


def _userns_available() -> bool:
    """Unprivileged user namespace with a subuid range, a mount namespace and setpriv."""
    if os.geteuid() == 0 or not all(shutil.which(t) for t in ("unshare", "setpriv")):
        return False
    r = subprocess.run(
        ["unshare", "--map-root-user", "--map-auto", "--mount", "true"],
        capture_output=True,
        check=False,
    )
    return r.returncode == 0


USERNS_SCRIPT = r"""
set -euo pipefail
umask 022
tmp="$1"
# A passwd/group the installer's user lands in, as useradd --system would make it.
cp /etc/passwd "$tmp/passwd"; cp /etc/group "$tmp/group"
mount --bind "$tmp/passwd" /etc/passwd; mount --bind "$tmp/group" /etc/group
mkdir -p "$tmp/bin"
cat >"$tmp/bin/useradd" <<'SH'
#!/bin/bash
echo "xonotic-webui:x:4242:4242::/var/lib/xonotic-webui:/usr/sbin/nologin" >>/etc/passwd
echo "xonotic-webui:x:4242:" >>/etc/group
SH
chmod +x "$tmp/bin/useradd"
export PATH="$tmp/bin:$PATH"
# A tmpfs so every path component is traversable by the service user.
mount -t tmpfs tmpfs /mnt
export DESTDIR=/mnt/dest
source "$INSTALL"
ensure_user; ensure_user
ensure_dirs; ensure_dirs
# The release tree the helper is installed from.
SRC="$tmp/rel/xonotic-webui"; mkdir -p "$SRC/deploy"
cp "$(dirname "$INSTALL")"/xonotic-webui-upgrade* "$SRC/deploy/"
install_upgrade_helper; install_upgrade_helper
mkdir -p "$GAME_DIR/data" "$PREFIX/venv/bin"
printf '#!/bin/sh\n' >"$GAME_DIR/xonotic-linux64-dedicated"
chmod 0755 "$GAME_DIR/xonotic-linux64-dedicated"
echo d >"$GAME_DIR/data/a.pk3"; echo x >"$PREFIX/venv/bin/python"
chmod 0755 "$PREFIX/venv/bin/python"
repair_ownership; verify_layout; echo VERIFIED
stat -c 'OWNER %U:%G %a %n' "$PREFIX" "$GAME_PARENT" "$GAME_DIR" \
  "$STATE_DIR" "$USERDIR" "$USERDIR/data" "$REQUEST_DIR" "$HELPER_DIR" "$HELPER" \
  "$HELPER_STATUS_DIR" "$UNIT_DIR/xonotic-webui-upgrade.path" \
  "$UNIT_DIR/xonotic-webui-upgrade.service"
for d in "$PREFIX" "$PREFIX/venv" "$GAME_PARENT" "$GAME_DIR" "$GAME_DIR/data" "$ETC_DIR" \
  "$HELPER_DIR" "$HELPER_STATUS_DIR"; do
  as_service_user touch "$d/probe" 2>/dev/null && echo "WROTE $d" || echo "DENIED $d"
done
for d in "$STATE_DIR" "$USERDIR" "$USERDIR/data" "$REQUEST_DIR"; do
  as_service_user touch "$d/probe" && echo "ALLOWED $d" || echo "BLOCKED $d"
done
# the helper, its units and its status: readable, never writable, by the service user
as_service_user test -r "$HELPER_STATUS_DIR" && echo "READABLE status" || echo "UNREADABLE status"
as_service_user test -r "$HELPER" && echo "READABLE helper" || echo "UNREADABLE helper"
as_service_user test -w "$HELPER" && echo "WRITABLE helper" || echo "PROTECTED helper"
for u in xonotic-webui-upgrade.path xonotic-webui-upgrade.service; do
  as_service_user test -w "$UNIT_DIR/$u" && echo "WRITABLE $u" || echo "PROTECTED $u"
done
# the service user places a request, root can read it (and it cannot replace the helper)
as_service_user sh -c "echo '{}' >'$REQUEST_DIR/request.json'" && echo "REQUEST-PLACED"
as_service_user sh -c "echo x >'$HELPER'" 2>/dev/null \
  && echo "HELPER-OVERWRITTEN" || echo "HELPER-INTACT"
as_service_user sh -c "echo x >'$HELPER_STATUS_DIR/status.json'" 2>/dev/null \
  && echo "STATUS-FORGED" || echo "STATUS-UNFORGEABLE"
rm -f "$REQUEST_DIR/request.json"
# sabotage: a group-writable app file, a service-user-owned game file, a root-owned state file
chmod 0777 "$PREFIX/venv/bin"; chown 4242:4242 "$GAME_DIR/data/a.pk3"
echo cfg >"$USERDIR/data/server.cfg"
if ( verify_layout ) 2>/dev/null; then echo "MISSED-SABOTAGE"; else echo "CAUGHT-SABOTAGE"; fi
repair_ownership; verify_layout; echo REPAIRED
stat -c 'OWNER %U %n' "$GAME_DIR/data/a.pk3" "$USERDIR/data/server.cfg"
# sabotage the helper: owned by the service user, then its unit group-writable
chown 4242:4242 "$HELPER"
if ( verify_layout ) 2>/dev/null; then echo "MISSED-HELPER"; else echo "CAUGHT-HELPER"; fi
repair_ownership; verify_layout; echo HELPER-REPAIRED
stat -c 'OWNER %U %n' "$HELPER"
chmod 0666 "$UNIT_DIR/xonotic-webui-upgrade.path"
if ( verify_layout ) 2>/dev/null; then echo "MISSED-UNIT"; else echo "CAUGHT-UNIT"; fi
repair_ownership; verify_layout; echo UNIT-REPAIRED
chown 4242:4242 "$PREFIX"
if ( verify_layout ) 2>/dev/null; then echo MISSED-OWNED-PREFIX
else echo CAUGHT-OWNED-PREFIX; fi
"""


@pytest.mark.skipif(not _userns_available(), reason="needs unprivileged user namespaces + subuid")
def test_layout_is_enforced_for_real_in_a_user_namespace(tmp_path: Path) -> None:
    """Ownership and the service user's inability to write the app tree, for real.

    Runs the installer's own functions as (namespace) root with a real, distinct service
    uid: `install -o`, `chown` and the kernel's permission checks are not stubbed."""
    r = subprocess.run(
        [
            "unshare",
            "--map-root-user",
            "--map-auto",
            "--mount",
            "bash",
            "-c",
            USERNS_SCRIPT,
            "bash",
            str(tmp_path),
        ],
        env={**os.environ, "INSTALL": str(INSTALL)},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "VERIFIED" in out
    for rel in ("opt/xonotic-webui", "opt/xonotic", "opt/xonotic/0.8.6"):
        assert f"OWNER root:root 755 /mnt/dest/{rel}\n" in out, out
    for rel in ("var/lib/xonotic-webui", "var/lib/xonotic-webui/userdir"):
        assert f"OWNER xonotic-webui:xonotic-webui 755 /mnt/dest/{rel}\n" in out, out
    assert out.count("DENIED") == 8
    assert "WROTE" not in out
    assert out.count("ALLOWED") == 4
    assert "BLOCKED" not in out
    # the upgrade helper: root's, with the request directory the service user's
    assert "OWNER xonotic-webui:xonotic-webui 755 /mnt/dest/var/lib/xonotic-webui/upgrade\n" in out
    assert "OWNER root:root 755 /mnt/dest/usr/local/libexec/xonotic-webui\n" in out
    assert (
        "OWNER root:root 755 /mnt/dest/usr/local/libexec/xonotic-webui/xonotic-webui-upgrade\n"
        in out
    )
    assert "OWNER root:root 755 /mnt/dest/var/lib/xonotic-webui-upgrade\n" in out
    assert "OWNER root:root 644 /mnt/dest/etc/systemd/system/xonotic-webui-upgrade.path\n" in out
    assert "OWNER root:root 644 /mnt/dest/etc/systemd/system/xonotic-webui-upgrade.service\n" in out
    assert "READABLE status" in out and "UNREADABLE" not in out
    assert "READABLE helper" in out
    assert "PROTECTED helper" in out and "WRITABLE" not in out
    assert out.count("PROTECTED") == 3
    assert "REQUEST-PLACED" in out
    assert "HELPER-INTACT" in out and "HELPER-OVERWRITTEN" not in out
    assert "STATUS-UNFORGEABLE" in out and "STATUS-FORGED" not in out
    assert "CAUGHT-HELPER" in out and "HELPER-REPAIRED" in out
    assert "OWNER root /mnt/dest/usr/local/libexec/xonotic-webui/xonotic-webui-upgrade" in out
    assert "CAUGHT-UNIT" in out and "UNIT-REPAIRED" in out
    assert "MISSED" not in out
    assert "CAUGHT-SABOTAGE" in out
    assert "REPAIRED" in out
    assert "OWNER root /mnt/dest/opt/xonotic/0.8.6/data/a.pk3" in out
    assert "OWNER xonotic-webui /mnt/dest/var/lib/xonotic-webui/userdir/data/server.cfg" in out
    assert "CAUGHT-OWNED-PREFIX" in out


# --- 9.4 the game -----------------------------------------------------------------------------


def test_matching_local_archive_is_extracted_minimally(sb: Sandbox) -> None:
    archive = sb.tmp / "game.zip"
    digest = make_game_zip(archive)
    r = sb.call(
        f'XONOTIC_SHA256="{digest}"; mkdir -p "$GAME_PARENT" "$CACHE_DIR"; install_game',
        XONOTIC_ARCHIVE=str(archive),
    )
    assert r.returncode == 0, r.stderr
    game = sb.root / "opt" / "xonotic" / "0.8.6"
    assert (game / "xonotic-linux64-dedicated").stat().st_mode & stat.S_IXUSR
    assert (game / "key_0.d0pk").is_file()
    assert (game / "data" / "xonotic-test-data.pk3").is_file()
    assert (game / "data" / "xonotic-test-maps.pk3").is_file()
    # what a dedicated server does not need is left behind
    assert not (game / "data" / "xonotic-test-music.pk3").exists()
    assert not (game / "xonotic.exe").exists()
    assert not (game / "source").exists()
    assert archive.exists(), "a user-supplied archive is never deleted"
    assert not (sb.root / "opt" / "xonotic" / ".staging-0.8.6").exists()


def test_local_archive_is_used_instead_of_downloading(sb: Sandbox) -> None:
    archive = sb.tmp / "game.zip"
    digest = make_game_zip(archive)
    sb.shim("curl", "exit 22")  # any download attempt fails the install
    r = sb.call(
        f'XONOTIC_SHA256="{digest}"; mkdir -p "$GAME_PARENT" "$CACHE_DIR"; install_game',
        XONOTIC_ARCHIVE=str(archive),
    )
    assert r.returncode == 0, r.stderr
    assert sb.called("curl") == []
    assert (sb.root / "opt" / "xonotic" / "0.8.6" / "xonotic-linux64-dedicated").is_file()


def test_digest_mismatch_fails_and_leaves_no_unverified_files(sb: Sandbox) -> None:
    archive = sb.tmp / "corrupt.zip"
    make_game_zip(archive)
    # verified against the real pinned digest, which this archive cannot match
    r = sb.call('mkdir -p "$GAME_PARENT" "$CACHE_DIR"; install_game', XONOTIC_ARCHIVE=str(archive))
    assert r.returncode != 0
    assert "digest mismatch" in r.stderr
    assert PINNED in r.stderr
    parent = sb.root / "opt" / "xonotic"
    assert list(parent.iterdir()) == [], "no staging or game files may remain"
    assert archive.exists(), "a user-supplied archive is left alone"


def test_corrupt_download_is_removed_so_it_is_not_resumed_forever(sb: Sandbox) -> None:
    served = sb.tmp / "served.zip"
    make_game_zip(served)
    # curl shim: "download" by copying a corrupt archive and reporting the pinned size
    sb.shim(
        "curl",
        'out=""; while [ $# -gt 0 ]; do [ "$1" = -o ] && out="$2"; shift; done; '
        f'cp "{served}" "$out"',
    )
    size = served.stat().st_size
    r = sb.call(f'XONOTIC_SIZE_BYTES={size}; mkdir -p "$GAME_PARENT" "$CACHE_DIR"; install_game')
    assert r.returncode != 0
    assert "digest mismatch" in r.stderr
    assert not (sb.root / "var" / "cache" / "xonotic-webui" / "xonotic-0.8.6.zip").exists()
    assert sb.called("curl"), "the archive should have been downloaded"


def test_installed_game_is_not_downloaded_again(sb: Sandbox) -> None:
    sb.shim("curl", "exit 22")
    r = sb.call(
        'mkdir -p "$GAME_DIR/data"; echo x > "$GAME_DIR/xonotic-linux64-dedicated"; '
        'chmod +x "$GAME_DIR/xonotic-linux64-dedicated"; install_game'
    )
    assert r.returncode == 0, r.stderr
    assert sb.called("curl") == []
    assert "not downloading it again" in r.stdout


def test_a_complete_cached_archive_is_not_fetched_again(sb: Sandbox) -> None:
    archive_src = sb.tmp / "good.zip"
    digest = make_game_zip(archive_src)
    sb.shim("curl", "exit 22")  # any download attempt fails the test
    size = archive_src.stat().st_size
    r = sb.call(
        f'XONOTIC_SHA256="{digest}"; XONOTIC_SIZE_BYTES={size}; '
        'mkdir -p "$GAME_PARENT" "$CACHE_DIR"; '
        f'cp "{archive_src}" "$CACHE_DIR/xonotic-0.8.6.zip"; install_game'
    )
    assert r.returncode == 0, r.stderr
    assert sb.called("curl") == []


# --- 9.6 configuration ---------------------------------------------------------------------------


def test_server_cfg_is_seeded_with_the_event_log_enabled(sb: Sandbox) -> None:
    r = sb.call('mkdir -p "$USERDIR/data"; SERVICE_USER=$(id -un); seed_server_cfg')
    assert r.returncode == 0, r.stderr
    cfg = (sb.root / "var/lib/xonotic-webui/userdir/data/server.cfg").read_text()
    assert "sv_eventlog 1" in cfg
    assert "sv_eventlog_console 1" in cfg
    assert "hostname" in cfg


def test_existing_server_cfg_is_never_overwritten(sb: Sandbox) -> None:
    cfg = sb.root / "var/lib/xonotic-webui/userdir/data/server.cfg"
    cfg.parent.mkdir(parents=True)
    original = b'// my own config\nhostname "Mine"\nsv_eventlog 0\n'
    cfg.write_bytes(original)
    for _ in range(2):  # a re-run, twice
        r = sb.call("SERVICE_USER=$(id -un); seed_server_cfg")
        assert r.returncode == 0, r.stderr
    assert cfg.read_bytes() == original


def test_env_file_is_seeded_once(sb: Sandbox) -> None:
    sb.call('mkdir -p "$ETC_DIR"; seed_env_file')
    env_file = sb.root / "etc/xonotic-webui/xonotic-webui.env"
    assert env_file.is_file()
    env_file.write_text("XONOTIC_WEBUI_PORT=8080\n")
    sb.call("seed_env_file")
    assert env_file.read_text() == "XONOTIC_WEBUI_PORT=8080\n"


# --- the upgrade helper ----------------------------------------------------------------


def _shim_install(sb: Sandbox) -> None:
    """A stand-in for install(1): directories, or copy-then-chmod, ignoring -o/-g."""
    sb.shim(
        "install",
        r"""
mode=""; dirs=0; ops=()
while [ $# -gt 0 ]; do
  case "$1" in
    -d) dirs=1 ;;
    -m) mode="$2"; shift ;;
    -o|-g) shift ;;
    *) ops+=("$1") ;;
  esac
  shift
done
if [ "$dirs" -eq 1 ]; then
  mkdir -p "${ops[@]}"
  [ -n "$mode" ] && chmod "$mode" "${ops[@]}"
else
  cp "${ops[0]}" "${ops[1]}"
  [ -n "$mode" ] && chmod "$mode" "${ops[1]}"
fi
exit 0
""",
    )


def _release_tree(sb: Sandbox, *, with_helper: bool = True) -> Path:
    src = sb.tmp / "rel" / "xonotic-webui"
    deploy = src / "deploy"
    deploy.mkdir(parents=True, exist_ok=True)
    (deploy / "xonotic-webui.service").write_text("[Service]\n")
    if with_helper:
        for name in (
            "xonotic-webui-upgrade",
            "xonotic-webui-upgrade.path",
            "xonotic-webui-upgrade.service",
        ):
            shutil.copy(ROOT / "deploy" / name, deploy / name)
    return src


HELPER_REL = "usr/local/libexec/xonotic-webui/xonotic-webui-upgrade"


def test_fresh_install_installs_the_helper_units_and_directories(sb: Sandbox) -> None:
    _shim_install(sb)
    src = _release_tree(sb)
    r = sb.call(f'SRC="{src}"; install_upgrade_helper')
    assert r.returncode == 0, r.stderr
    helper = sb.root / HELPER_REL
    assert helper.is_file()
    assert helper.stat().st_mode & 0o777 == 0o755
    assert (sb.root / "var/lib/xonotic-webui-upgrade").is_dir()
    assert (sb.root / "var/lib/xonotic-webui/upgrade").is_dir()
    for unit in ("xonotic-webui-upgrade.path", "xonotic-webui-upgrade.service"):
        installed = sb.root / "etc/systemd/system" / unit
        assert installed.read_text() == (ROOT / "deploy" / unit).read_text()
        assert installed.stat().st_mode & 0o777 == 0o644


def test_the_helper_is_bound_to_the_default_repository(sb: Sandbox) -> None:
    _shim_install(sb)
    src = _release_tree(sb)
    assert sb.call(f'SRC="{src}"; install_upgrade_helper').returncode == 0
    lines = [
        ln for ln in (sb.root / HELPER_REL).read_text().splitlines() if ln.startswith("REPO = ")
    ]
    assert lines == ['REPO = "carlhako/xonotic-webui"']


def test_the_helper_is_bound_to_a_custom_repository(sb: Sandbox) -> None:
    _shim_install(sb)
    src = _release_tree(sb)
    r = sb.call(f'SRC="{src}"; install_upgrade_helper', XONOTIC_WEBUI_REPO="someone/xonotic-fork")
    assert r.returncode == 0, r.stderr
    lines = [
        ln for ln in (sb.root / HELPER_REL).read_text().splitlines() if ln.startswith("REPO = ")
    ]
    assert lines == ['REPO = "someone/xonotic-fork"']


@pytest.mark.parametrize(
    "repo",
    ['evil"; touch /pwned #/x', "no-slash", "a/b/c", "a b/c", "a/b|c", "", "../x", "a/b&c"],
)
def test_a_repository_that_is_not_owner_slash_name_is_refused(sb: Sandbox, repo: str) -> None:
    r = sb.call("require_repo", XONOTIC_WEBUI_REPO=repo)
    if repo == "":
        # empty means "use the default"
        assert r.returncode == 0
        return
    assert r.returncode != 0
    assert "owner/name" in r.stderr


def test_rerunning_over_an_install_without_the_helper_adds_it(sb: Sandbox) -> None:
    """A v0.1.x install: the application is there, the helper is not."""
    _shim_install(sb)
    prefix = sb.root / "opt" / "xonotic-webui"
    (prefix / "venv" / "bin").mkdir(parents=True)
    assert not (sb.root / HELPER_REL).exists()
    src = _release_tree(sb)
    assert sb.call(f'SRC="{src}"; install_upgrade_helper').returncode == 0
    assert (sb.root / HELPER_REL).is_file()
    # and again: refreshing is idempotent
    (sb.root / HELPER_REL).write_text("stale")
    assert sb.call(f'SRC="{src}"; install_upgrade_helper').returncode == 0
    assert "stale" not in (sb.root / HELPER_REL).read_text()


def test_a_release_without_the_helper_leaves_things_as_they_are(sb: Sandbox) -> None:
    _shim_install(sb)
    src = _release_tree(sb, with_helper=False)
    r = sb.call(f'SRC="{src}"; install_upgrade_helper')
    assert r.returncode == 0, r.stderr
    assert "no upgrade helper" in r.stderr
    assert not (sb.root / "usr/local").exists()
    assert not (sb.root / "var/lib/xonotic-webui-upgrade").exists()


def test_the_helper_trigger_is_enabled_when_the_panel_is_started(sb: Sandbox) -> None:
    _shim_install(sb)
    src = _release_tree(sb)
    _prepare_swap(sb, previous=True)
    sb.shim("curl", 'echo \'{"status":"ok","version":"9.9.9"}\'')
    r = sb.call(f'SRC="{src}"; install_upgrade_helper; {SWAP.format(src=src)}')
    assert r.returncode == 0, r.stderr
    calls = sb.called("systemctl")
    assert "systemctl enable --now xonotic-webui-upgrade.path" in calls
    enable_path = calls.index("systemctl enable --now xonotic-webui-upgrade.path")
    assert enable_path < calls.index("systemctl start xonotic-webui.service")


def test_no_trigger_is_enabled_for_a_release_without_the_helper(sb: Sandbox) -> None:
    src = _release_tree(sb, with_helper=False)
    _prepare_swap(sb, previous=True)
    sb.shim("curl", 'echo \'{"status":"ok","version":"9.9.9"}\'')
    r = sb.call(SWAP.format(src=src))
    assert r.returncode == 0, r.stderr
    assert not [c for c in sb.called("systemctl") if "upgrade.path" in c]


DROPIN = "etc/systemd/system/xonotic-webui.service.d/release-repo.conf"


def test_default_repository_writes_no_dropin_and_removes_a_stale_one(sb: Sandbox) -> None:
    stale = sb.root / DROPIN
    stale.parent.mkdir(parents=True)
    stale.write_text("[Service]\nEnvironment=XONOTIC_WEBUI_RELEASE_REPO=someone/old\n")
    r = sb.call("sync_release_repo")
    assert r.returncode == 0, r.stderr
    assert not stale.exists()
    assert not stale.parent.exists()  # the emptied drop-in directory goes too
    # and with nothing there to begin with, nothing appears
    assert sb.call("sync_release_repo").returncode == 0
    assert not stale.parent.exists()


def test_custom_repository_points_the_panel_at_it(sb: Sandbox) -> None:
    _shim_install(sb)
    r = sb.call("sync_release_repo", XONOTIC_WEBUI_REPO="someone/fork")
    assert r.returncode == 0, r.stderr
    conf = sb.root / DROPIN
    assert conf.read_text() == "[Service]\nEnvironment=XONOTIC_WEBUI_RELEASE_REPO=someone/fork\n"
    assert conf.stat().st_mode & 0o777 == 0o644
    # changing it again replaces the value
    sb.call("sync_release_repo", XONOTIC_WEBUI_REPO="another/fork")
    assert "another/fork" in conf.read_text()
    assert "someone/fork" not in conf.read_text()


def test_a_dropin_the_operator_set_via_the_env_file_still_wins() -> None:
    # The drop-in uses Environment=; the unit's EnvironmentFile= overrides it.
    unit = UNIT.read_text()
    assert "EnvironmentFile=-/etc/xonotic-webui/xonotic-webui.env" in unit


def test_main_checks_the_repository_before_changing_anything() -> None:
    text = INSTALL.read_text()
    main = text[text.index("\nmain() {") :]
    assert main.index("require_repo") < main.index("install_packages")
    assert main.index("install_upgrade_helper") < main.index("verify_layout")
    assert main.index("sync_release_repo") < main.index("swap_and_start")


# --- 9.7 swap, health, rollback, report -------------------------------------------------


def _prepare_swap(sb: Sandbox, *, previous: bool) -> None:
    prefix = sb.root / "opt" / "xonotic-webui"
    (prefix / "venv.new" / "bin").mkdir(parents=True)
    (prefix / "venv.new" / "marker").write_text("new")
    if previous:
        (prefix / "venv" / "bin").mkdir(parents=True)
        (prefix / "venv" / "marker").write_text("old")
    src = sb.tmp / "rel" / "xonotic-webui" / "deploy"
    src.mkdir(parents=True, exist_ok=True)
    (src / "xonotic-webui.service").write_text("[Service]\n")
    for name in ("systemctl", "sleep"):
        sb.shim(name, "exit 0")
    sb.shim("xargs", "cat >/dev/null")


SWAP = 'NEW_VENV="$PREFIX/venv.new"; NEW_VERSION=9.9.9; SRC="{src}"; swap_and_start'


def test_swap_installs_the_new_version_when_it_answers(sb: Sandbox) -> None:
    _prepare_swap(sb, previous=True)
    sb.shim("curl", 'echo \'{"status":"ok","version":"9.9.9"}\'')
    r = sb.call(SWAP.format(src=sb.tmp / "rel" / "xonotic-webui"))
    assert r.returncode == 0, r.stderr
    prefix = sb.root / "opt" / "xonotic-webui"
    assert (prefix / "venv" / "marker").read_text() == "new"
    assert not (prefix / "venv.old").exists()
    assert (sb.root / "etc/systemd/system/xonotic-webui.service").is_file()
    assert any(c.startswith("systemctl enable") for c in sb.called("systemctl"))


def test_bad_release_restores_the_previous_version_and_exits_nonzero(sb: Sandbox) -> None:
    _prepare_swap(sb, previous=True)
    sb.shim("curl", "exit 7")  # the new panel never answers
    r = sb.call(SWAP.format(src=sb.tmp / "rel" / "xonotic-webui"))
    assert r.returncode != 0
    assert "previous version is running again" in r.stderr
    prefix = sb.root / "opt" / "xonotic-webui"
    assert (prefix / "venv" / "marker").read_text() == "old"
    assert not (prefix / "venv.new").exists()
    assert not (prefix / "venv.failed").exists()
    # the old unit was put back and the service started again
    starts = [c for c in sb.called("systemctl") if c.startswith("systemctl start")]
    assert len(starts) == 2


def test_fresh_install_that_does_not_answer_fails(sb: Sandbox) -> None:
    _prepare_swap(sb, previous=False)
    sb.shim("curl", "exit 7")
    r = sb.call(SWAP.format(src=sb.tmp / "rel" / "xonotic-webui"))
    assert r.returncode != 0
    assert "did not start" in r.stderr


def test_report_prints_the_web_url_and_game_port(sb: Sandbox) -> None:
    sb.shim("hostname", 'if [ "${1:-}" = -I ]; then echo "192.0.2.10 "; else echo box; fi')
    r = sb.call("NEW_VERSION=1.2.3; report")
    assert r.returncode == 0
    assert "http://192.0.2.10/" in r.stdout
    assert "UDP 26000" in r.stdout


def test_report_honours_configured_ports(sb: Sandbox) -> None:
    sb.shim("hostname", 'if [ "${1:-}" = -I ]; then echo "192.0.2.10 "; else echo box; fi')
    sb.call('mkdir -p "$ETC_DIR"')
    (sb.root / "etc/xonotic-webui").mkdir(parents=True, exist_ok=True)
    (sb.root / "etc/xonotic-webui/xonotic-webui.env").write_text(
        "XONOTIC_WEBUI_PORT=8080\nXONOTIC_WEBUI_GAME_PORT=27000\n"
    )
    r = sb.call("NEW_VERSION=1.2.3; report")
    assert "http://192.0.2.10:8080/" in r.stdout
    assert "UDP 27000" in r.stdout


# --- 9.1 unit file ----------------------------------------------------------------------


def test_unit_is_valid_and_stop_timeout_exceeds_the_worst_case_shutdown() -> None:
    r = subprocess.run(
        ["systemd-analyze", "verify", str(UNIT)], capture_output=True, text=True, check=False
    )
    # The only complaint allowed is about files that exist on the target, not here.
    problems = [
        line
        for line in (r.stdout + r.stderr).splitlines()
        if line.strip() and "is not executable: No such file or directory" not in line
    ]
    assert problems == [], problems

    text = UNIT.read_text()
    timeout = int(
        next(x for x in text.splitlines() if x.startswith("TimeoutStopSec=")).split("=")[1]
    )
    # uvicorn drain 10 + SHUTDOWN_TIMEOUT 60 + SIGTERM grace 5 + SIGKILL wait 10
    assert timeout > 10 + 60 + 5 + 10
    assert "KillMode=mixed" in text
    assert "Restart=on-failure" in text
    assert "User=xonotic-webui" in text
    assert "AmbientCapabilities=CAP_NET_BIND_SERVICE" in text
    assert "CapabilityBoundingSet=CAP_NET_BIND_SERVICE" in text
    assert "NoNewPrivileges=true" in text
    assert "ProtectSystem=strict" in text


def test_unit_paths_match_the_installer_layout() -> None:
    unit = UNIT.read_text()
    script = INSTALL.read_text()
    assert "/opt/xonotic-webui/venv/bin/python -m xonotic_webui" in unit
    assert "XONOTIC_WEBUI_GAME_ROOT=/opt/xonotic/0.8.6" in unit
    assert "XONOTIC_WEBUI_STATE_DIR=/var/lib/xonotic-webui" in unit
    assert "EnvironmentFile=-/etc/xonotic-webui/xonotic-webui.env" in unit
    assert 'PREFIX="${DESTDIR}/opt/${APP_NAME}"' in script
    assert 'GAME_PARENT="${DESTDIR}/opt/xonotic"' in script


# --- 9.5 fetching the panel release ---------------------------------------------------


def _make_tarball(path: Path, version: str = "1.2.3") -> Path:
    import io
    import tarfile

    with tarfile.open(path, "w:gz") as tf:
        for name, data in {
            f"xonotic-webui/dist/xonotic_webui-{version}-py3-none-any.whl": b"wheel",
            "xonotic-webui/deploy/xonotic-webui.service": b"[Service]\n",
        }.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return path


def test_offline_tarball_is_used_without_any_download(sb: Sandbox) -> None:
    tarball = _make_tarball(sb.tmp / "xonotic-webui.tar.gz", "4.5.6")
    sb.shim("curl", "exit 22")
    r = sb.call(
        'fetch_release; echo "version=$NEW_VERSION"; echo "wheel=$WHEEL"',
        XONOTIC_WEBUI_TARBALL=str(tarball),
    )
    assert r.returncode == 0, r.stderr
    assert "version=4.5.6" in r.stdout
    assert "xonotic_webui-4.5.6-py3-none-any.whl" in r.stdout
    assert sb.called("curl") == []


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        (None, "/releases/latest/download/xonotic-webui.tar.gz"),
        ("v0.3.0", "/releases/download/v0.3.0/xonotic-webui.tar.gz"),
    ],
)
def test_release_tag_pins_the_download(sb: Sandbox, tag: str | None, expected: str) -> None:
    tarball = _make_tarball(sb.tmp / "served.tar.gz")
    sb.shim(
        "curl",
        'out=""; while [ $# -gt 0 ]; do [ "$1" = -o ] && out="$2"; shift; done; '
        f'cp "{tarball}" "$out"',
    )
    extra = {"RELEASE_TAG": tag} if tag else {}
    r = sb.call('fetch_release; echo "version=$NEW_VERSION"', **extra)
    assert r.returncode == 0, r.stderr
    url = next(c for c in sb.called("curl"))
    assert "github.com/carlhako/xonotic-webui" in url
    assert expected in url
    assert "version=1.2.3" in r.stdout


def test_a_tarball_without_a_wheel_is_rejected(sb: Sandbox) -> None:
    import tarfile

    empty = sb.tmp / "empty.tar.gz"
    with tarfile.open(empty, "w:gz"):
        pass
    r = sb.call("fetch_release", XONOTIC_WEBUI_TARBALL=str(empty))
    assert r.returncode != 0
    assert "no xonotic-webui wheel" in r.stderr
