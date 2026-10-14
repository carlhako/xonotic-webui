"""The README names files the code actually uses."""

from __future__ import annotations

import re
from pathlib import Path

from xonotic_webui.settings import APP_NAME, DEFAULT_GAME_ROOT, DEFAULT_STATE_DIR, Settings
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
        str(s.players_db),
        str(s.userdir / "data" / "server.cfg"),
        str(s.userdir / "data" / SETTINGS_CONFIG_NAME),
    }
    assert expected <= _documented_paths()


def test_the_documented_settings_file_names() -> None:
    assert SETTINGS_CONFIG_NAME == "xonotic-webui-settings.cfg"
    assert Settings().game_settings_file.name == "settings.json"
    assert "`xonotic-webui-settings.cfg`" in README


def test_the_upgrade_helper_and_state_files_are_documented_where_the_code_has_them() -> None:
    s = Settings(state_dir=DEFAULT_STATE_DIR, game_root=DEFAULT_GAME_ROOT)
    expected = {
        str(s.upgrade_helper_path),
        str(s.upgrade_status_dir / "status.json"),
        str(s.state_dir / "release_check.json"),
        str(s.upgrade_request_dir / "request.json"),
        str(s.state_dir / "upgrade_pending.json"),
        f"/etc/systemd/system/{APP_NAME}-upgrade.path",
        f"/etc/systemd/system/{APP_NAME}-upgrade.service",
        f"/etc/systemd/system/{APP_NAME}.service.d/release-repo.conf",
    }
    assert expected <= _documented_paths()


def test_every_documented_setting_is_a_real_setting_with_its_default() -> None:
    names = set(re.findall(r"^\| `(XONOTIC_WEBUI_[A-Z_]+)` \|", README, flags=re.MULTILINE))
    fields = {n.upper() for n in Settings.model_fields}
    unknown = {n for n in names if n.removeprefix("XONOTIC_WEBUI_") not in fields | {"CONFIG_FILE"}}
    assert not unknown, unknown
    # and the self-update settings are all in the table
    for field in (
        "release_repo",
        "release_api_url",
        "release_check_enabled",
        "release_check_interval_hours",
        "upgrade_helper_path",
        "upgrade_status_dir",
        "upgrade_timeout_seconds",
        "user_agent",
    ):
        assert f"XONOTIC_WEBUI_{field.upper()}" in names, field


def test_the_documented_defaults_match_the_settings() -> None:
    s = Settings()
    row = dict(re.findall(r"^\| `(XONOTIC_WEBUI_[A-Z_]+)` \| `([^`]+)` \|", README, re.MULTILINE))
    assert row["XONOTIC_WEBUI_RELEASE_REPO"] == s.release_repo
    assert row["XONOTIC_WEBUI_RELEASE_API_URL"] == s.release_api_url
    assert row["XONOTIC_WEBUI_RELEASE_CHECK_ENABLED"] == str(s.release_check_enabled).lower()
    assert (
        float(row["XONOTIC_WEBUI_RELEASE_CHECK_INTERVAL_HOURS"]) == s.release_check_interval_hours
    )
    assert row["XONOTIC_WEBUI_UPGRADE_HELPER_PATH"] == str(s.upgrade_helper_path)
    assert row["XONOTIC_WEBUI_UPGRADE_STATUS_DIR"] == str(s.upgrade_status_dir)
    assert float(row["XONOTIC_WEBUI_UPGRADE_TIMEOUT_SECONDS"]) == s.upgrade_timeout_seconds


def test_the_manual_upgrade_command_is_the_one_the_panel_shows() -> None:
    from xonotic_webui.selfupdate.upgrade import manual_command

    assert manual_command(Settings()) in README


def test_the_players_section_names_the_reserved_report_cvar_and_the_xonstat_trade_off() -> None:
    from xonotic_webui.serversettings.registry import FORCED_CVARS

    value = dict(FORCED_CVARS)["g_playerstats_gamereport_uri"]
    assert f"`g_playerstats_gamereport_uri` to `{value}`" in README
    assert "XonStat" in README
    assert "## Players" in README
    assert "players.db" in README
