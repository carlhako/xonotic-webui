"""Settings precedence (env over TOML over defaults) and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from xonotic_webui.settings import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_GAME_ROOT,
    DEFAULT_STATE_DIR,
    Settings,
)

ENV_KEYS = [
    "PORT",
    "HOST",
    "GAME_PORT",
    "GAME_ROOT",
    "STATE_DIR",
    "SHUTDOWN_TIMEOUT",
    "READINESS_TIMEOUT",
    "CRASH_RESTART_THRESHOLD",
    "CRASH_RESTART_WINDOW",
    "CRASH_RESTART_DELAY",
    "CONSOLE_BUFFER_LINES",
    "CONFIG_FILE",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ENV_KEYS:
        monkeypatch.delenv(f"XONOTIC_WEBUI_{key}", raising=False)
    # Never read the real /etc file on a developer machine.
    monkeypatch.setenv("XONOTIC_WEBUI_CONFIG_FILE", "/nonexistent/xonotic-webui.toml")


def _toml(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "cfg.toml"
    path.write_text(body)
    return path


def test_defaults_match_design() -> None:
    s = Settings()
    assert s.port == 80
    assert s.host == "0.0.0.0"
    assert s.game_port == 26000
    assert s.game_root == DEFAULT_GAME_ROOT
    assert s.state_dir == DEFAULT_STATE_DIR
    assert s.shutdown_timeout == 60
    assert s.readiness_timeout == 120
    assert s.crash_restart_threshold == 3
    assert s.crash_restart_window == 300
    assert s.userdir == DEFAULT_STATE_DIR / "userdir"
    assert s.state_file == DEFAULT_STATE_DIR / "state.json"
    assert s.game_binary.name == "xonotic-linux64-dedicated"


def test_default_config_path_is_derived_from_app_name() -> None:
    assert DEFAULT_CONFIG_FILE == Path("/etc/xonotic-webui/xonotic-webui.toml")


def test_toml_overrides_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _toml(tmp_path, "port = 8081\ngame_port = 26111\n")
    monkeypatch.setenv("XONOTIC_WEBUI_CONFIG_FILE", str(cfg))
    s = Settings()
    assert s.port == 8081
    assert s.game_port == 26111
    assert s.host == "0.0.0.0"  # untouched default


def test_toml_section_form_is_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _toml(tmp_path, "[xonotic_webui]\nport = 8082\n")
    monkeypatch.setenv("XONOTIC_WEBUI_CONFIG_FILE", str(cfg))
    assert Settings().port == 8082


def test_env_overrides_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _toml(tmp_path, "port = 8081\nshutdown_timeout = 30\n")
    monkeypatch.setenv("XONOTIC_WEBUI_CONFIG_FILE", str(cfg))
    monkeypatch.setenv("XONOTIC_WEBUI_PORT", "9090")
    s = Settings()
    assert s.port == 9090  # env wins
    assert s.shutdown_timeout == 30  # toml still applies where env is silent


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("PORT", "0"),
        ("PORT", "70000"),
        ("PORT", "eighty"),
        ("GAME_PORT", "-1"),
        ("SHUTDOWN_TIMEOUT", "0"),
        ("READINESS_TIMEOUT", "0.5"),
        ("CRASH_RESTART_THRESHOLD", "-1"),
        ("CRASH_RESTART_WINDOW", "0"),
    ],
)
def test_invalid_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    monkeypatch.setenv(f"XONOTIC_WEBUI_{key}", value)
    with pytest.raises(ValidationError):
        Settings()


def test_invalid_toml_value_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _toml(tmp_path, "port = 99999\n")
    monkeypatch.setenv("XONOTIC_WEBUI_CONFIG_FILE", str(cfg))
    with pytest.raises(ValidationError):
        Settings()


def test_zero_threshold_is_valid_and_disables_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XONOTIC_WEBUI_CRASH_RESTART_THRESHOLD", "0")
    assert Settings().crash_restart_threshold == 0
