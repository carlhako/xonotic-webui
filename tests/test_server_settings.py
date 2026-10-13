"""Saving settings, applying them live and reading live values (server-settings spec)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.helpers import make_settings
from xonotic_webui.console.buffer import LineKind
from xonotic_webui.console.console import Console, InternalQueryError
from xonotic_webui.serversettings.registry import ApplyClass
from xonotic_webui.serversettings.service import (
    ReservedCvarError,
    ServerSettingsService,
    SettingsError,
    UnknownSettingError,
)
from xonotic_webui.serversettings.store import SettingsStore
from xonotic_webui.settings import Settings
from xonotic_webui.supervisor import NotRunningError, RunState, Supervisor


@dataclass
class Rig:
    settings: Settings
    sup: Supervisor
    console: Console
    svc: ServerSettingsService

    @property
    def cfg(self) -> str:
        return (self.settings.userdir / "data" / "xonotic-webui-settings.cfg").read_text()

    def stored(self) -> dict:
        return json.loads(self.settings.game_settings_file.read_text())

    def commands(self) -> list[str]:
        return [ln.text for ln in self.console.buffer.snapshot() if ln.kind is LineKind.COMMAND]

    def output(self) -> list[str]:
        return [ln.plain for ln in self.console.buffer.snapshot() if ln.kind is LineKind.OUTPUT]

    async def wait_output(self, text: str, timeout: float = 5.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while not any(text in line for line in self.output()):
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError(f"{text!r} not seen in the console")
            await asyncio.sleep(0.02)


@pytest.fixture
async def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Rig]:
    monkeypatch.delenv("FAKE_XONOTIC", raising=False)
    settings = make_settings(tmp_path)
    sup = Supervisor(settings, probe_after=0.5, probe_interval=0.3)
    console = Console(sup)
    svc = ServerSettingsService(
        settings, sup, console, SettingsStore(settings.game_settings_file), query_timeout=3.0
    )
    sup.set_settings_cfg(svc.render_config)
    yield Rig(settings, sup, console, svc)
    await sup.aclose()


@pytest.fixture
async def make_rig(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Callable[..., Rig]]:
    monkeypatch.delenv("FAKE_XONOTIC", raising=False)
    made: list[Supervisor] = []

    def factory(**overrides: object) -> Rig:
        settings = make_settings(tmp_path, **overrides)
        sup = Supervisor(settings, probe_after=0.5, probe_interval=0.3)
        console = Console(sup)
        svc = ServerSettingsService(
            settings, sup, console, SettingsStore(settings.game_settings_file), query_timeout=0.4
        )
        sup.set_settings_cfg(svc.render_config)
        made.append(sup)
        return Rig(settings, sup, console, svc)

    yield factory
    for sup in made:
        await sup.aclose()


# --- persistence and precedence --------------------------------------------------------


async def test_setting_changed_while_stopped_is_saved_and_applied_at_the_next_start(
    rig: Rig,
) -> None:
    result = await rig.svc.patch({"hostname": "LAN Party"})
    assert result == {"hostname": ApplyClass.NEXT_START}
    assert rig.stored()["values"] == {"hostname": "LAN Party"}
    assert 'hostname "LAN Party"' in rig.cfg

    await rig.sup.start()
    live = await rig.svc.live_values(["hostname"])
    assert live == {"hostname": "LAN Party"}


async def test_a_setting_survives_a_server_restart(rig: Rig) -> None:
    await rig.sup.start()
    await rig.svc.patch({"hostname": "LAN Party"})
    await rig.sup.restart()
    assert await rig.svc.live_values(["hostname"]) == {"hostname": "LAN Party"}


async def test_the_generated_config_is_rewritten_on_every_start(rig: Rig) -> None:
    await rig.sup.start()
    await rig.sup.stop()
    # edited behind the panel's back (e.g. restored from a backup): next start regenerates
    rig.svc.store.path.write_text(json.dumps({"version": 1, "values": {"skill": 3}}))
    await rig.sup.start()
    assert 'skill "3"' in rig.cfg


async def test_a_fresh_install_leaves_the_server_to_its_own_config(rig: Rig) -> None:
    await rig.sup.start()
    assert not rig.settings.game_settings_file.exists()
    assert rig.cfg.startswith("// Managed by")
    assert all(ln.startswith("//") for ln in rig.cfg.splitlines())


async def test_server_cfg_is_never_modified(rig: Rig) -> None:
    server_cfg = rig.settings.userdir / "data" / "server.cfg"
    server_cfg.parent.mkdir(parents=True)
    server_cfg.write_text('hostname "Old Name"\ntimelimit_override 20\n')
    before = server_cfg.read_text()
    await rig.sup.start()
    await rig.svc.patch({"hostname": "New", "timelimit_override": 10})
    await rig.svc.put_override("g_x", "1")
    assert server_cfg.read_text() == before


async def test_panel_values_win_over_server_cfg_and_the_overlap_is_shown(rig: Rig) -> None:
    server_cfg = rig.settings.userdir / "data" / "server.cfg"
    server_cfg.parent.mkdir(parents=True)
    server_cfg.write_text('hostname "Old Name"\ntimelimit_override 20\n')
    await rig.svc.patch({"timelimit_override": 10})
    await rig.sup.start()
    live = await rig.svc.live_values(["timelimit_override", "hostname"])
    assert live["timelimit_override"] == "10"  # panel's 10 beats server.cfg's 20
    assert live["hostname"] == "Old Name"  # no panel value: server.cfg applies

    flagged = {s.setting.key: s.server_cfg for s in await rig.svc.view()}
    assert flagged["hostname"] and flagged["timelimit_override"]
    assert not flagged["skill"]


async def test_a_corrupt_settings_file_does_not_stop_the_server_starting(rig: Rig) -> None:
    rig.settings.game_settings_file.parent.mkdir(parents=True, exist_ok=True)
    rig.settings.game_settings_file.write_text("{broken")
    await rig.sup.start()
    assert rig.sup.state is RunState.RUNNING
    assert rig.settings.game_settings_file.read_text() == "{broken"
    markers = [ln.text for ln in rig.console.buffer.snapshot() if ln.kind is LineKind.MARKER]
    assert any("panel settings not applied" in m for m in markers)


# --- when each change takes effect --------------------------------------------------


async def test_an_immediate_setting_is_applied_to_the_running_server_and_echoed(rig: Rig) -> None:
    await rig.sup.start()
    result = await rig.svc.patch({"hostname": "LAN Party"})
    assert result == {"hostname": ApplyClass.NOW}
    assert 'hostname "LAN Party"' in rig.commands()  # visible in the console history
    assert await rig.svc.live_values(["hostname"]) == {"hostname": "LAN Party"}


async def test_a_next_map_setting_applies_to_the_next_map(rig: Rig) -> None:
    await rig.sup.start()
    result = await rig.svc.patch({"g_instagib": True})
    assert result == {"g_instagib": ApplyClass.NEXT_MAP}
    await rig.console.submit_command("changelevel boil")
    await rig.wait_output(":gameinfo:mutators:LIST:instagib:norecoil")


async def test_maxplayers_is_a_next_start_setting_and_applies_after_a_restart(rig: Rig) -> None:
    await rig.sup.start()
    result = await rig.svc.patch({"maxplayers": 8})
    assert result == {"maxplayers": ApplyClass.NEXT_START}
    await rig.wait_output("maxplayers can not be changed while a server is running")
    await rig.sup.restart()
    assert await rig.svc.live_values(["maxplayers"]) == {"maxplayers": "8"}


async def test_the_result_names_the_class_of_every_changed_key(rig: Rig) -> None:
    await rig.sup.start()
    result = await rig.svc.patch({"hostname": "x", "g_instagib": True, "maxplayers": 4, "skill": 3})
    assert result == {
        "hostname": ApplyClass.NOW,
        "g_instagib": ApplyClass.NEXT_MAP,
        "maxplayers": ApplyClass.NEXT_START,
        "skill": ApplyClass.NOW,
    }


async def test_limits_apply_to_the_current_match_and_survive_a_map_change(rig: Rig) -> None:
    await rig.sup.start()
    result = await rig.svc.patch({"timelimit_override": 10, "fraglimit_override": 50})
    assert result == {
        "timelimit_override": ApplyClass.NOW,
        "fraglimit_override": ApplyClass.NOW,
    }
    live = await rig.svc.live_values(["timelimit", "fraglimit"])
    assert live == {"timelimit": "10", "fraglimit": "50"}  # the current match
    assert 'timelimit "10"' in rig.commands()

    await rig.console.submit_command("changelevel boil")
    await rig.wait_output(":gamestart:dm_boil:")
    live = await rig.svc.live_values(["timelimit", "fraglimit"])
    assert live == {"timelimit": "10", "fraglimit": "50"}  # the next map


async def test_a_limit_set_back_to_map_default_takes_effect_at_the_next_map(rig: Rig) -> None:
    await rig.sup.start()
    await rig.svc.patch({"timelimit_override": 10})
    result = await rig.svc.patch({"timelimit_override": None})
    assert result == {"timelimit_override": ApplyClass.NEXT_MAP}
    assert "timelimit_override" not in rig.stored()["values"]
    assert "timelimit_override" not in rig.cfg
    assert (await rig.svc.live_values(["timelimit_override"]))["timelimit_override"] == "-1"
    await rig.console.submit_command("changelevel boil")
    await rig.wait_output(":gamestart:dm_boil:")
    assert (await rig.svc.live_values(["timelimit"]))["timelimit"] == "15"  # the map's own


async def test_unit_label_data_is_available_for_the_score_limit() -> None:
    from xonotic_webui.serversettings.registry import CURATED_BY_KEY, GAMETYPES_BY_ID

    assert CURATED_BY_KEY["fraglimit_override"].unit == "score"
    assert GAMETYPES_BY_ID["ctf"].score_unit == "captures"
    assert GAMETYPES_BY_ID["dm"].score_unit == "frags"


# --- validation ----------------------------------------------------------------------------


async def test_out_of_range_is_rejected_with_the_range_and_nothing_is_saved(rig: Rig) -> None:
    with pytest.raises(SettingsError, match="between 0 and 10") as err:
        await rig.svc.patch({"hostname": "ok", "skill": 99})
    assert err.value.field == "skill"
    assert not rig.settings.game_settings_file.exists()


@pytest.mark.parametrize(
    ("value", "named"),
    [("a\nb", "line break"), ('say "x"', "double quote"), ("a\\b", "backslash")],
)
async def test_rejected_characters_are_named(rig: Rig, value: str, named: str) -> None:
    with pytest.raises(SettingsError, match=named):
        await rig.svc.patch({"sv_motd": value})
    assert not rig.settings.game_settings_file.exists()


async def test_wrong_types_and_unknown_keys(rig: Rig) -> None:
    with pytest.raises(SettingsError, match="whole number"):
        await rig.svc.patch({"skill": 3.5})
    with pytest.raises(SettingsError, match="on or off"):
        await rig.svc.patch({"g_instagib": "yes"})
    with pytest.raises(SettingsError, match="a number"):
        await rig.svc.patch({"skill": True})
    with pytest.raises(UnknownSettingError):
        await rig.svc.patch({"not_a_setting": 1})
    with pytest.raises(SettingsError, match="no settings"):
        await rig.svc.patch({})


async def test_auto_pause_is_reported_on_until_changed(rig: Rig) -> None:
    states = {s.setting.key: s for s in await rig.svc.view()}
    assert states["sv_autopause"].value is None  # never changed...
    assert states["sv_autopause"].setting.default is True  # ...so the enabled default applies


# --- injection and the real round trip ---------------------------------------------------


async def test_values_with_console_syntax_arrive_verbatim_and_run_nothing(rig: Rig) -> None:
    await rig.sup.start()
    await rig.svc.patch({"sv_motd": "Welcome; have fun", "hostname": "$hostname rocks"})
    live = await rig.svc.live_values(["sv_motd", "hostname"])
    assert live == {"sv_motd": "Welcome; have fun", "hostname": "$hostname rocks"}
    assert not any('Unknown command "have' in line for line in rig.output())

    # the same values from the generated config at the next start
    await rig.sup.restart()
    live = await rig.svc.live_values(["sv_motd", "hostname"])
    assert live == {"sv_motd": "Welcome; have fun", "hostname": "$hostname rocks"}
    assert not any('Unknown command "have' in line for line in rig.output())


async def test_colour_codes_are_accepted_and_kept(rig: Rig) -> None:
    await rig.sup.start()
    await rig.svc.patch({"hostname": "^1Red ^xF80Server"})
    assert await rig.svc.live_values(["hostname"]) == {"hostname": "^1Red ^xF80Server"}


# --- raw overrides --------------------------------------------------------------------------


async def test_add_change_and_remove_an_override(rig: Rig) -> None:
    await rig.sup.start()
    result = await rig.svc.put_override("g_balance_health_start", "150")
    assert result is ApplyClass.MAY_NEED_RESTART
    assert 'set g_balance_health_start "150"' in rig.commands()
    assert rig.stored()["overrides"] == {"g_balance_health_start": "150"}
    assert 'set g_balance_health_start "150"' in rig.cfg
    (item,) = await rig.svc.overrides()
    assert (item.name, item.value, item.live_value) == ("g_balance_health_start", "150", "150")

    await rig.svc.put_override("g_balance_health_start", "175")
    assert rig.stored()["overrides"] == {"g_balance_health_start": "175"}

    assert await rig.svc.delete_override("g_balance_health_start") is ApplyClass.NEXT_START
    assert rig.stored()["overrides"] == {}
    assert "g_balance_health_start" not in rig.cfg


async def test_unknown_cvars_can_be_overridden_too(rig: Rig) -> None:
    await rig.sup.start()
    await rig.svc.put_override("my_mod_option", "x y")
    assert await rig.svc.live_values(["my_mod_option"]) == {"my_mod_option": "x y"}


async def test_an_override_saved_while_stopped_is_next_start(rig: Rig) -> None:
    assert await rig.svc.put_override("g_x", "1") is ApplyClass.NEXT_START


@pytest.mark.parametrize("name", ["sv_eventlog", "SV_EVENTLOG_CONSOLE", "port", "rcon_password"])
async def test_reserved_cvars_are_refused_and_nothing_is_saved(rig: Rig, name: str) -> None:
    with pytest.raises(ReservedCvarError, match="reserved") as err:
        await rig.svc.put_override(name, "0")
    assert err.value.field == name
    assert not rig.settings.game_settings_file.exists()


@pytest.mark.parametrize("name", ["has space", "semi;colon", "", 'quo"te'])
async def test_invalid_override_names_are_rejected(rig: Rig, name: str) -> None:
    with pytest.raises(SettingsError):
        await rig.svc.put_override(name, "1")
    assert not rig.settings.game_settings_file.exists()


async def test_override_values_are_validated_like_any_other(rig: Rig) -> None:
    with pytest.raises(SettingsError, match="double quote"):
        await rig.svc.put_override("g_x", 'a"b')


# --- the catalogue and live values -------------------------------------------------------


async def test_search_while_stopped_has_defaults_and_descriptions_only(rig: Rig) -> None:
    page = await rig.svc.search_cvars("maplist")
    assert page.total >= 21
    first = page.items[0]
    assert first.entry.description
    assert all(item.live_value is None for item in page.items)


async def test_search_while_running_adds_current_values(rig: Rig) -> None:
    await rig.sup.start()
    await rig.svc.put_override("g_maplist_votable", "3")
    page = await rig.svc.search_cvars("g_maplist_votable", limit=20)
    by_name = {i.entry.name: i for i in page.items}
    assert by_name["g_maplist_votable"].live_value == "3"
    assert by_name["g_maplist_votable"].override == "3"
    assert by_name["g_maplist_votable_timeout"].live_value == "30"


async def test_browsing_the_catalogue_leaves_the_console_history_alone(rig: Rig) -> None:
    await rig.sup.start()
    await rig.wait_output(":gameinfo:end")
    before = [ln.text for ln in rig.console.buffer.snapshot()]
    seen: list[str] = []
    for query in ("maplist", "bot", "limit"):
        page = await rig.svc.search_cvars(query, limit=20)
        assert any(i.live_value is not None for i in page.items)
    stream = rig.console.stream()
    try:
        async with asyncio.timeout(0.5):
            async for line in stream:
                seen.append(line.text)
    except TimeoutError:
        pass
    finally:
        await stream.aclose()
    assert seen == before  # none of the replies (nor commands) reached clients


async def test_unknown_names_come_back_as_none(rig: Rig) -> None:
    await rig.sup.start()
    values = await rig.svc.live_values(["hostname", "no_such_cvar_xyz"])
    assert values == {"hostname": "fake xonotic", "no_such_cvar_xyz": None}


async def test_live_values_raise_when_the_server_does_not_answer_in_time(
    make_rig: Callable[..., Rig],
) -> None:
    rig = make_rig()
    await rig.sup.start()
    # ``status`` answers, but not in the shape of a cvar read: the query times out
    with pytest.raises(InternalQueryError):
        await rig.svc.live_values(["status"])
    # and the console and the server are left usable
    assert await rig.svc.live_values(["hostname"]) == {"hostname": "fake xonotic"}


async def test_live_values_need_a_running_server(rig: Rig) -> None:
    with pytest.raises(NotRunningError):
        await rig.svc.live_values(["hostname"])
    # views degrade instead of failing
    states = await rig.svc.view()
    assert all(s.live_value is None for s in states)
