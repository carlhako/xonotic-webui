"""Settings precedence (env over TOML over defaults) and validation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from xonotic_webui import __version__
from xonotic_webui.settings import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_GAME_ROOT,
    DEFAULT_STATE_DIR,
    Settings,
)

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"

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
    "RELEASE_REPO",
    "RELEASE_API_URL",
    "RELEASE_CHECK_ENABLED",
    "RELEASE_CHECK_INTERVAL_HOURS",
    "UPGRADE_HELPER_PATH",
    "UPGRADE_STATUS_DIR",
    "UPGRADE_TIMEOUT_SECONDS",
    "USER_AGENT",
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
def test_invalid_values_are_rejected(monkeypatch: pytest.MonkeyPatch, key: str, value: str) -> None:
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


def test_self_update_defaults() -> None:
    s = Settings()
    assert s.release_repo == "carlhako/xonotic-webui"
    assert s.release_api_url == "https://api.github.com"
    assert s.release_check_enabled is True
    assert s.release_check_interval_hours == 12
    assert s.upgrade_helper_path == Path("/usr/local/libexec/xonotic-webui/xonotic-webui-upgrade")
    assert s.upgrade_status_dir == Path("/var/lib/xonotic-webui-upgrade")
    assert s.upgrade_timeout_seconds == 3900
    assert s.upgrade_request_dir == DEFAULT_STATE_DIR / "upgrade"
    assert s.user_agent == (
        f"xonotic-webui/{__version__} (+https://github.com/carlhako/xonotic-webui)"
    )


def test_self_update_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XONOTIC_WEBUI_RELEASE_REPO", "someone/fork")
    monkeypatch.setenv("XONOTIC_WEBUI_RELEASE_CHECK_ENABLED", "false")
    monkeypatch.setenv("XONOTIC_WEBUI_RELEASE_CHECK_INTERVAL_HOURS", "1.5")
    monkeypatch.setenv("XONOTIC_WEBUI_UPGRADE_STATUS_DIR", str(tmp_path / "status"))
    monkeypatch.setenv("XONOTIC_WEBUI_STATE_DIR", str(tmp_path / "state"))
    s = Settings()
    assert s.release_repo == "someone/fork"
    assert s.release_check_enabled is False
    assert s.release_check_interval_hours == 1.5
    assert s.upgrade_status_dir == tmp_path / "status"
    assert s.upgrade_request_dir == tmp_path / "state" / "upgrade"
    # The default user agent follows the repository the panel is pointed at.
    assert s.user_agent.endswith("(+https://github.com/someone/fork)")


def test_explicit_user_agent_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XONOTIC_WEBUI_USER_AGENT", "custom/1")
    assert Settings().user_agent == "custom/1"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("RELEASE_CHECK_INTERVAL_HOURS", "0"),
        ("UPGRADE_TIMEOUT_SECONDS", "0"),
        ("RELEASE_REPO", "not-a-repo"),
        ("RELEASE_REPO", "../x"),
        ("RELEASE_REPO", "a/b/c"),
    ],
)
def test_invalid_self_update_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    monkeypatch.setenv(f"XONOTIC_WEBUI_{key}", value)
    with pytest.raises(ValidationError):
        Settings()


def test_upgrade_timeout_exceeds_the_helper_units_timeout() -> None:
    """The panel must not give up on a helper that systemd would still let run."""
    unit = (DEPLOY / "xonotic-webui-upgrade.service").read_text()
    match = re.search(r"^TimeoutStartSec=(\d+)min\s*$", unit, re.MULTILINE)
    assert match, "the helper unit must state TimeoutStartSec in whole minutes"
    assert Settings().upgrade_timeout_seconds > int(match.group(1)) * 60
