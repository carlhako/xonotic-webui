"""Shared test helpers: a game root that runs the fake dedicated server."""

from __future__ import annotations

import json
import os
import stat
import sys
import zipfile
from pathlib import Path

from xonotic_webui.settings import GAME_BINARY_NAME, Settings

FAKE_SERVER = Path(__file__).parent / "fake_xonotic" / "server.py"
FAKE_MAPS = Path(__file__).parent / "fake_xonotic" / "maps.json"

# A stand-in for a preview image: the catalogue only streams the bytes.
PREVIEW_BYTES = b"\xff\xd8\xff\xe0fake-jpeg"


def fake_maps() -> dict[str, list[str]]:
    """The installed maps the fake server knows: name -> gametypes."""
    return json.loads(FAKE_MAPS.read_text())


def write_pk3(path: Path, maps: dict[str, dict | None]) -> Path:
    """Write a map package. Each value describes one map:

    ``title``, ``description``, ``author``, ``gametypes`` (list), ``hidden`` (bool),
    ``mapinfo`` (False to omit the file) and ``preview`` ("jpg", "png" or ``None``).
    ``None`` is a map with defaults.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, spec in maps.items():
            spec = spec or {}
            zf.writestr(f"maps/{name}.bsp", b"BSP")
            if spec.get("mapinfo", True):
                lines = [f"title {spec.get('title', name.title())}"]
                if "description" in spec:
                    lines.append(f"description {spec['description']}")
                if "author" in spec:
                    lines.append(f"author {spec['author']}")
                lines += [f"gametype {g} 20 5 5" for g in spec.get("gametypes", ["dm"])]
                if spec.get("hidden"):
                    lines.append("hidden")
                zf.writestr(f"maps/{name}.mapinfo", "\n".join(lines) + "\n")
            if spec.get("preview", "jpg"):
                zf.writestr(f"maps/{name}.{spec.get('preview', 'jpg')}", PREVIEW_BYTES)
    return path


def install_fake_maps(game_root: Path) -> Path:
    """Install the fake server's map table as a stock-like package (plus ``_hudsetup``)."""
    specs: dict[str, dict | None] = {
        name: {"title": name.replace("_", " ").title(), "gametypes": gametypes}
        for name, gametypes in fake_maps().items()
    }
    specs["_hudsetup"] = {"gametypes": ["dm"]}
    return write_pk3(game_root / "data" / "xonotic-data-maps.pk3", specs)


def make_game_root(tmp_path: Path) -> Path:
    """A directory whose ``xonotic-linux64-dedicated`` is the fake server."""
    root = tmp_path / "game"
    root.mkdir(parents=True, exist_ok=True)
    exe = root / GAME_BINARY_NAME
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_SERVER}" "$@"\n')
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    install_fake_maps(root)
    return root


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    """Settings pointing at a tmp state dir and the fake game root, with fast timeouts."""
    values: dict[str, object] = {
        "game_root": make_game_root(tmp_path),
        "state_dir": tmp_path / "state",
        "game_port": 26999,
        "port": 18080,
        "host": "127.0.0.1",
        "shutdown_timeout": 5.0,
        "readiness_timeout": 10.0,
        "crash_restart_delay": 0.0,
        "console_buffer_lines": 500,
        # The suite never contacts GitHub or depends on a helper installed on the host.
        "release_check_enabled": False,
        "upgrade_helper_path": tmp_path / "libexec" / "xonotic-webui-upgrade",
        "upgrade_status_dir": tmp_path / "upgrade-status",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def process_alive(pid: int) -> bool:
    """True if ``pid`` exists and is not a zombie."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
    return state != "Z"
