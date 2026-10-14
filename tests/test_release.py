"""The release artifact: a wheel carrying the prebuilt interface, assembled and installed
the way the workflow and the installer do it, with no Node and no compiler involved."""

from __future__ import annotations

import os
import socket
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "deploy" / "install.sh"
STATIC_INDEX = ROOT / "src" / "xonotic_webui" / "static" / "index.html"

if sys.platform != "linux":  # pragma: no cover
    pytest.skip("linux-only deploy assets", allow_module_level=True)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Build the frontend (if needed), the wheel and the release assets."""
    if not STATIC_INDEX.is_file():
        if not (ROOT / "web" / "node_modules").is_dir():
            pytest.skip("no built frontend and no node_modules to build one")
        subprocess.run(
            ["npm", "--prefix", "web", "run", "build"], cwd=ROOT, check=True, capture_output=True
        )
    dist = ROOT / "dist"
    for old in dist.glob("xonotic_webui-*.whl"):
        old.unlink()
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=300,
    )
    out = tmp_path_factory.mktemp("release")
    subprocess.run(
        [str(ROOT / "scripts" / "assemble-release.sh"), str(out)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return {
        "wheel": next(dist.glob("xonotic_webui-*-py3-none-any.whl")),
        "tarball": out / "xonotic-webui.tar.gz",
        "installer": out / "install.sh",
    }


def test_wheel_carries_the_prebuilt_interface_and_no_source(built: dict[str, Path]) -> None:
    names = zipfile.ZipFile(built["wheel"]).namelist()
    assert "xonotic_webui/static/index.html" in names
    assert any(n.startswith("xonotic_webui/static/assets/") for n in names)
    assert "xonotic_webui/__main__.py" in names
    assert not any(n.endswith((".ts", ".tsx")) for n in names)


def test_tarball_is_wheel_plus_docs_and_deploy_assets(built: dict[str, Path]) -> None:
    names = tarfile.open(built["tarball"]).getnames()
    assert any(
        n.startswith("xonotic-webui/dist/xonotic_webui-") and n.endswith(".whl") for n in names
    )
    for asset in (
        "deploy/install.sh",
        "deploy/xonotic-webui.service",
        "deploy/xonotic-webui-upgrade",
        "deploy/xonotic-webui-upgrade.path",
        "deploy/xonotic-webui-upgrade.service",
        "README.md",
        "LICENSE",
    ):
        assert f"xonotic-webui/{asset}" in names, asset
    for n in names:
        assert "/web/" not in n and "node_modules" not in n, n
        assert not n.endswith((".ts", ".tsx")), n


def test_both_release_assets_are_produced(built: dict[str, Path]) -> None:
    assert built["tarball"].stat().st_size > 10_000
    assert built["installer"].read_bytes() == INSTALL.read_bytes()


def _have_network() -> bool:
    try:
        socket.create_connection(("pypi.org", 443), timeout=5).close()
    except OSError:
        return False
    return True


@pytest.mark.skipif(not _have_network(), reason="needs PyPI")
def test_install_needs_no_node_and_no_compiler(built: dict[str, Path], tmp_path: Path) -> None:
    """Run the installer's own venv build with node and every compiler booby-trapped."""
    trap = tmp_path / "trap"
    trap.mkdir()
    log = tmp_path / "trap.log"
    for tool in ("node", "npm", "npx", "gcc", "cc", "g++", "c++", "make", "cargo", "rustc"):
        shim = trap / tool
        shim.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{log}"\nexit 99\n')
        shim.chmod(shim.stat().st_mode | stat.S_IXUSR)

    dest = tmp_path / "dest"
    (dest / "opt" / "xonotic-webui").mkdir(parents=True)
    script = f"""
set -euo pipefail
source "{INSTALL}"
WHEEL="{built["wheel"]}"
NEW_VERSION="test"
build_venv
"$PREFIX/venv.new/bin/python" -c "import xonotic_webui, fastapi, uvicorn, pydantic_settings; \
print(xonotic_webui.__version__)"
"""
    r = subprocess.run(
        ["bash", "-c", script],
        env={**os.environ, "DESTDIR": str(dest), "PATH": f"{trap}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    # A bare `--version` is a library probing its environment (pydantic asks for rustc
    # when reporting versions), not a build; anything else would be a real invocation.
    calls = log.read_text().splitlines() if log.exists() else []
    builds = [c for c in calls if not c.endswith(" --version")]
    assert builds == [], f"a build tool was invoked: {builds}"
    # the app was installed with its interface, ready to start with no build step
    venv = dest / "opt" / "xonotic-webui" / "venv.new"
    static = next(venv.glob("lib/python*/site-packages/xonotic_webui/static/index.html"))
    assert static.is_file()


# --- changelog and release notes (panel-self-update) ----------------------------------

NOTES_SCRIPT = ROOT / ".github" / "scripts" / "release-notes.sh"
CHANGELOG = ROOT / "CHANGELOG.md"

SAMPLE = """# Changelog

Preamble that belongs to no release.

## 0.2.0 - 2026-10-20

### What's new

- the **panel** page
- one-click upgrades

## 0.1.10 - 2026-10-15

- ten

## 0.1.1 - 2026-10-13

- one-one

## 0.1.0 - 2026-10-12

## 0.0.9 - 2026-10-01
- nine
"""


def _notes(
    tmp_path: Path, version: str, changelog: str = SAMPLE
) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(changelog)
    return subprocess.run(
        ["bash", str(NOTES_SCRIPT), version, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_notes_script_prints_a_present_section(tmp_path: Path) -> None:
    r = _notes(tmp_path, "0.2.0")
    assert r.returncode == 0, r.stderr
    assert r.stdout == "### What's new\n\n- the **panel** page\n- one-click upgrades\n"


def test_notes_script_accepts_a_v_prefixed_tag(tmp_path: Path) -> None:
    assert _notes(tmp_path, "v0.2.0").stdout == _notes(tmp_path, "0.2.0").stdout


def test_notes_script_fails_naming_a_missing_version(tmp_path: Path) -> None:
    r = _notes(tmp_path, "0.3.0")
    assert r.returncode != 0
    assert "0.3.0" in r.stderr
    assert r.stdout == ""


def test_notes_script_fails_on_an_empty_section(tmp_path: Path) -> None:
    r = _notes(tmp_path, "0.1.0")  # a heading with nothing under it
    assert r.returncode != 0
    assert "0.1.0" in r.stderr
    assert r.stdout == ""


def test_notes_script_does_not_confuse_a_version_with_a_longer_one(tmp_path: Path) -> None:
    only_long = "# Changelog\n\n## 0.1.10 - 2026-10-15\n\n- ten\n"
    assert _notes(tmp_path, "0.1.1", only_long).returncode != 0
    both = _notes(tmp_path, "0.1.1")
    assert both.returncode == 0
    assert both.stdout == "- one-one\n"
    assert _notes(tmp_path, "0.1.10").stdout == "- ten\n"


def test_notes_script_needs_a_version_and_a_changelog(tmp_path: Path) -> None:
    no_args = subprocess.run(["bash", str(NOTES_SCRIPT)], capture_output=True, text=True)
    assert no_args.returncode == 2
    missing = subprocess.run(
        ["bash", str(NOTES_SCRIPT), "0.1.0", str(tmp_path / "nope.md")],
        capture_output=True,
        text=True,
    )
    assert missing.returncode != 0


def _project_version() -> str:
    import tomllib

    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def test_the_project_version_has_a_changelog_section() -> None:
    version = _project_version()
    r = subprocess.run(
        ["bash", str(NOTES_SCRIPT), version, str(CHANGELOG)], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip()


def test_every_changelog_section_has_content() -> None:
    import re

    versions = re.findall(r"^## (\S+)", CHANGELOG.read_text(), flags=re.MULTILINE)
    assert versions, "the changelog has no release sections"
    for version in versions:
        r = subprocess.run(
            ["bash", str(NOTES_SCRIPT), version, str(CHANGELOG)], capture_output=True, text=True
        )
        assert r.returncode == 0, f"{version}: {r.stderr}"


def test_the_package_version_and_the_project_version_agree() -> None:
    from xonotic_webui import __version__

    assert __version__ == _project_version()
