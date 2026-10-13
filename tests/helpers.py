"""Shared test helpers: a game root that runs the fake dedicated server."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from xonotic_webui.settings import GAME_BINARY_NAME, Settings

FAKE_SERVER = Path(__file__).parent / "fake_xonotic" / "server.py"


def make_game_root(tmp_path: Path) -> Path:
    """A directory whose ``xonotic-linux64-dedicated`` is the fake server."""
    root = tmp_path / "game"
    root.mkdir(parents=True, exist_ok=True)
    exe = root / GAME_BINARY_NAME
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_SERVER}" "$@"\n')
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
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
