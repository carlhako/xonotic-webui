"""The static registries are consistent with the captured game data."""

from __future__ import annotations

from pathlib import Path

import pytest

from xonotic_webui.serversettings.catalogue import build_from_cvarlist
from xonotic_webui.serversettings.registry import (
    CURATED,
    FORCED_CVARS,
    GAMETYPES,
    GROUPS,
    NOT_EDITABLE,
    RESERVED_CVARS,
    SECRET_CVARS,
    ApplyClass,
    is_reserved,
)
from xonotic_webui.serversettings.serialize import validate_name
from xonotic_webui.supervisor.supervisor import _WRAPPER_CONFIG

CVARLIST = Path(__file__).parent / "fixtures" / "xonotic" / "cvarlist.txt"

# ``maxplayers`` is a special cvar: the game does not list it in ``cvarlist`` and reads
# it back with no default part (transcripts/value_escaping_maxplayers_mutators.txt).
NOT_IN_CVARLIST = {"maxplayers"}


@pytest.fixture(scope="module")
def captured() -> dict[str, str]:
    """name -> default, from the captured ``cvarlist`` reply."""
    document = build_from_cvarlist(CVARLIST.read_text())
    return {e["name"]: e["default"] for e in document["cvars"]}


def test_every_curated_cvar_exists_in_the_captured_cvarlist(captured: dict[str, str]) -> None:
    for setting in CURATED:
        validate_name(setting.key)
        if setting.key not in NOT_IN_CVARLIST:
            assert setting.key in captured, setting.key
        if setting.live_cvar is not None:
            assert setting.live_cvar in captured, setting.live_cvar


def test_curated_defaults_are_the_games_defaults(captured: dict[str, str]) -> None:
    for setting in CURATED:
        if setting.key in NOT_IN_CVARLIST:
            continue
        assert setting.wire(setting.default) == captured[setting.key], setting.key


def test_curated_keys_are_unique_and_grouped() -> None:
    keys = [s.key for s in CURATED]
    assert len(keys) == len(set(keys))
    groups = {g for g, _ in GROUPS}
    assert {s.group for s in CURATED} <= groups
    assert groups == {s.group for s in CURATED}  # no empty tab


def test_curated_bounds_contain_the_default() -> None:
    for s in CURATED:
        if s.kind in ("int", "float"):
            assert s.min is not None and s.max is not None
            assert s.min <= s.default <= s.max, s.key


def test_the_required_curated_options_are_all_offered() -> None:
    keys = {s.key for s in CURATED}
    assert {
        "hostname",
        "sv_motd",
        "maxplayers",
        "sv_public",
        "timelimit_override",
        "fraglimit_override",
        "leadlimit_override",
        "g_warmup",
        "bot_number",
        "minplayers",
        "skill",
        "g_maplist_votable",
        "g_instagib",
        "sv_autopause",
    } <= keys
    # the statistics report target is forced by the panel, never a setting
    assert "g_playerstats_gamereport_uri" not in keys


def test_limits_are_the_override_cvars_and_apply_to_the_current_match_too() -> None:
    limits = {s.key: s for s in CURATED if s.unit is not None and s.key.endswith("_override")}
    assert {k: v.live_cvar for k, v in limits.items()} == {
        "timelimit_override": "timelimit",
        "fraglimit_override": "fraglimit",
        "leadlimit_override": "leadlimit",
    }
    assert all(s.default == -1 for s in limits.values())


def test_idle_auto_pause_defaults_on() -> None:
    (setting,) = [s for s in CURATED if s.key == "sv_autopause"]
    assert setting.default is True
    assert setting.apply is ApplyClass.NOW


def test_every_gametype_cvar_exists_in_the_captured_cvarlist(captured: dict[str, str]) -> None:
    assert len(GAMETYPES) == 20
    assert len({g.id for g in GAMETYPES}) == 20
    for gametype in GAMETYPES:
        assert gametype.cvar in captured, gametype.cvar
        assert gametype.name and gametype.score_unit


def test_the_wrapper_forces_exactly_the_reserved_cvars() -> None:
    forced = {name for name, _ in FORCED_CVARS}
    for name, value in FORCED_CVARS:
        assert f"\n{name} {value}\n" in _WRAPPER_CONFIG
    assert RESERVED_CVARS == forced | {"port"}
    assert SECRET_CVARS == {"rcon_password"}
    assert NOT_EDITABLE == RESERVED_CVARS | SECRET_CVARS
    assert is_reserved("SV_EVENTLOG") and is_reserved("rcon_password") and is_reserved("port")
    assert not is_reserved("hostname")


def test_no_curated_setting_is_reserved() -> None:
    assert not any(is_reserved(s.key) for s in CURATED)
