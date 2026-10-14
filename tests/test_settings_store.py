"""The settings store, the generated config and the server.cfg scan (design D1, D8, D11)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from xonotic_webui.serversettings.registry import CURATED_BY_KEY
from xonotic_webui.serversettings.servercfg import scan_server_cfg, scan_server_cfg_text
from xonotic_webui.serversettings.store import (
    CONFIG_HEADER,
    Rotation,
    SettingsStore,
    SettingsStoreError,
    StoreData,
    render_settings_cfg,
)

MAPS = {
    "stormkeep": frozenset({"dm", "tdm"}),
    "boil": frozenset({"dm", "tdm"}),
    "catharsis": frozenset({"ctf"}),
}


# --- the store -------------------------------------------------------------------------


def test_round_trip(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    data = StoreData(
        values={"hostname": "LAN Party", "skill": 5, "g_instagib": True},
        overrides={"g_balance_health_start": "150"},
        gametype="tdm",
        rotation=Rotation(["stormkeep", "boil"], False),
    )
    store.save(data)
    assert store.load() == data
    assert not (tmp_path / "settings.json.tmp").exists()  # written atomically


def test_a_missing_file_is_an_empty_store(tmp_path: Path) -> None:
    data = SettingsStore(tmp_path / "nope" / "settings.json").load()
    assert data == StoreData()
    assert data.rotation.shuffle is None


@pytest.mark.parametrize(
    "content",
    ["{not json", "[]", '{"values": []}', '{"rotation": {"maps": "x"}}', '{"gametype": 3}'],
)
def test_a_corrupt_file_is_an_error_and_is_left_alone(tmp_path: Path, content: str) -> None:
    path = tmp_path / "settings.json"
    path.write_text(content)
    store = SettingsStore(path)
    with pytest.raises(SettingsStoreError):
        store.load()
    assert path.read_text() == content


def test_saved_json_is_plain_and_versioned(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    store.save(StoreData(values={"hostname": "x"}))
    doc = json.loads((tmp_path / "settings.json").read_text())
    assert doc["version"] == 1
    assert doc["values"] == {"hostname": "x"}


# --- the generated config --------------------------------------------------------------


def test_an_empty_store_generates_a_header_only_file() -> None:
    text = render_settings_cfg(StoreData())
    assert text == CONFIG_HEADER
    assert all(line.startswith("//") for line in text.splitlines())


def test_saved_values_are_written_quoted_in_registry_order() -> None:
    data = StoreData(
        values={
            "skill": 5,
            "hostname": "LAN Party",
            "g_instagib": True,
            "g_norecoil": False,
            "timelimit_override": 10,
            "sv_public": False,
        }
    )
    lines = [ln for ln in render_settings_cfg(data).splitlines() if not ln.startswith("//")]
    order = [CURATED_BY_KEY[ln.split()[0]].key for ln in lines]
    assert order == [s.key for s in CURATED_BY_KEY.values() if s.key in data.values]
    assert 'hostname "LAN Party"' in lines
    assert 'skill "5"' in lines
    assert 'g_instagib "1"' in lines
    assert 'g_norecoil "0"' in lines
    assert 'timelimit_override "10"' in lines
    assert 'sv_public "0"' in lines


def test_hostile_values_cannot_start_a_second_command() -> None:
    data = StoreData(
        values={"sv_motd": "Welcome; have fun", "hostname": "$hostname rocks"},
        overrides={"g_test": "a // b; quit"},
    )
    lines = render_settings_cfg(data).splitlines()
    assert 'sv_motd "Welcome; have fun"' in lines
    assert 'hostname "$$hostname rocks"' in lines
    assert 'set g_test "a // b; quit"' in lines


def test_gametype_selection_sets_one_cvar_and_clears_the_rest() -> None:
    lines = render_settings_cfg(StoreData(gametype="tdm")).splitlines()
    assert "g_tdm 1" in lines
    assert "g_dm 0" in lines
    assert sum(1 for ln in lines if ln.endswith(" 1")) == 1
    assert sum(1 for ln in lines if ln.endswith(" 0")) == 19


def test_rotation_is_written_with_its_shuffle_flag() -> None:
    data = StoreData(rotation=Rotation(["stormkeep", "boil", "warfare"], False))
    lines = render_settings_cfg(data).splitlines()
    assert 'g_maplist "stormkeep boil warfare"' in lines
    assert "g_maplist_shuffle 0" in lines


def test_an_empty_rotation_writes_no_map_list() -> None:
    text = render_settings_cfg(StoreData(rotation=Rotation([], None)))
    assert "g_maplist" not in text


def test_maps_that_cannot_play_the_gametype_are_left_out() -> None:
    data = StoreData(gametype="tdm", rotation=Rotation(["stormkeep", "catharsis", "boil"], True))
    lines = render_settings_cfg(data, MAPS).splitlines()
    assert 'g_maplist "stormkeep boil"' in lines
    assert "g_maplist_shuffle 1" in lines
    # with no gametype chosen nothing can be judged, so the list is used as stored
    data.gametype = None
    assert 'g_maplist "stormkeep catharsis boil"' in render_settings_cfg(data, MAPS)


def test_raw_overrides_come_last_and_use_set() -> None:
    data = StoreData(
        values={"hostname": "curated"},
        overrides={"hostname": "raw", "g_a": "1"},
        gametype="dm",
    )
    lines = [ln for ln in render_settings_cfg(data).splitlines() if not ln.startswith("//")]
    assert lines.index('hostname "curated"') < lines.index('set hostname "raw"')
    assert lines[-1] == 'set hostname "raw"' or lines[-1] == 'set g_a "1"'
    assert lines.index("g_dm 1") < lines.index('set g_a "1"')


# --- the server.cfg scan -----------------------------------------------------------


def test_scan_finds_top_level_assignments() -> None:
    text = """\
// a comment
hostname "Old Name"
set sv_motd "hello // not a comment"   // trailing comment
seta g_instagib 1
timelimit_override 20
SV_PUBLIC "0"
"""
    assert scan_server_cfg_text(text) == {
        "hostname": "Old Name",
        "sv_motd": "hello // not a comment",
        "g_instagib": "1",
        "timelimit_override": "20",
        "sv_public": "0",
    }


def test_scan_ignores_what_it_cannot_judge() -> None:
    text = """\
exec other.cfg
alias fast "timelimit 5"
echo hostname "not set"
hostname
bind x "say hi"
if 1 "hostname y"
"with space" 5
last 1
last 2
"""
    assert scan_server_cfg_text(text) == {"last": "2"}


def test_scan_reads_a_file_and_tolerates_a_missing_one(tmp_path: Path) -> None:
    (tmp_path / "server.cfg").write_text('hostname "x"\n')
    assert scan_server_cfg(tmp_path / "server.cfg") == {"hostname": "x"}
    assert scan_server_cfg(tmp_path / "absent.cfg") == {}
