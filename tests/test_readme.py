"""The README names files the code actually uses."""

from __future__ import annotations

import re
from pathlib import Path

from xonotic_webui.settings import DEFAULT_GAME_ROOT, DEFAULT_STATE_DIR, Settings
from xonotic_webui.supervisor import SETTINGS_CONFIG_NAME

README = (Path(__file__).resolve().parent.parent / "README.md").read_text()


def _documented_paths() -> set[str]:
    return set(re.findall(r"^\| `(/[^`]+)` \|", README, flags=re.MULTILINE))


def test_the_where_things_live_paths_match_the_defaults() -> None:
    s = Settings(state_dir=DEFAULT_STATE_DIR, game_root=DEFAULT_GAME_ROOT)
    expected = {
        str(DEFAULT_GAME_ROOT),
        str(s.state_file),
        str(s.game_settings_file),
        str(s.userdir / "data" / "server.cfg"),
        str(s.userdir / "data" / SETTINGS_CONFIG_NAME),
    }
    assert expected <= _documented_paths()


def test_the_documented_settings_file_names() -> None:
    assert SETTINGS_CONFIG_NAME == "xonotic-webui-settings.cfg"
    assert Settings().game_settings_file.name == "settings.json"
    assert "`xonotic-webui-settings.cfg`" in README
