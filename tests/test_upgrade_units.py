"""The upgrade helper's units agree with the helper and with the panel's defaults."""

from __future__ import annotations

import configparser
import re
from pathlib import Path

from xonotic_webui.settings import APP_NAME, DEFAULT_STATE_DIR, Settings

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
HELPER = DEPLOY / f"{APP_NAME}-upgrade"
PATH_UNIT = DEPLOY / f"{APP_NAME}-upgrade.path"
SERVICE_UNIT = DEPLOY / f"{APP_NAME}-upgrade.service"


def _unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read_string(path.read_text())
    return parser


def _helper_default(name: str) -> str:
    """The default of ``name = os.environ.get("...", "<default>")`` in the helper."""
    match = re.search(
        rf'^{name} = os\.environ\.get\(\s*"[A-Z_]+",\s*"([^"]+)"', HELPER.read_text(), re.M
    )
    assert match, f"{name} not found in the helper"
    return match.group(1)


def test_path_unit_watches_the_request_file_the_panel_writes() -> None:
    settings = Settings()
    watched = _unit(PATH_UNIT)["Path"]["PathExists"]
    assert Path(watched) == settings.upgrade_request_dir / "request.json"
    assert Path(watched) == DEFAULT_STATE_DIR / "upgrade" / "request.json"
    assert _unit(PATH_UNIT)["Path"]["Unit"] == SERVICE_UNIT.name


def test_helper_reads_and_writes_where_the_panel_expects() -> None:
    settings = Settings()
    assert Path(_helper_default("REQUEST_DIR")) == settings.upgrade_request_dir
    assert Path(_helper_default("STATUS_DIR")) == settings.upgrade_status_dir


def test_service_unit_runs_the_helper_the_panel_looks_for() -> None:
    settings = Settings()
    service = _unit(SERVICE_UNIT)["Service"]
    interpreter, script = service["ExecStart"].split()
    assert interpreter == "/usr/bin/python3"  # the system python, never the venv
    assert Path(script) == settings.upgrade_helper_path
    assert service["Type"] == "oneshot"
    assert service["User"] == "root"
    assert service["TimeoutStartSec"] == "60min"


def test_service_unit_does_not_depend_on_the_panel() -> None:
    # The installer this unit runs restarts the panel; the unit must outlive that.
    text = SERVICE_UNIT.read_text()
    directives = [
        line
        for line in text.splitlines()
        if line.split("=", 1)[0]
        in {"Requires", "BindsTo", "PartOf", "After", "Wants", "Before", "Upholds"}
    ]
    assert not [d for d in directives if f"{APP_NAME}.service" in d]


def test_path_unit_is_enabled_with_the_system() -> None:
    assert _unit(PATH_UNIT)["Install"]["WantedBy"] == "multi-user.target"


def test_helper_is_executable_and_names_the_service_user() -> None:
    assert HELPER.stat().st_mode & 0o111
    assert _helper_default("SERVICE_USER") == APP_NAME
