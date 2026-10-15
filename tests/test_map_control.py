"""Gametype selection, the rotation and the match actions against the fake server."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

from tests.helpers import fake_maps, make_settings, write_pk3
from xonotic_webui.console.buffer import LineKind
from xonotic_webui.maps.actions import (
    ActionInProgressError,
    ActionMapGametypeError,
    ActionMapNotInstalledError,
    MapNotLoadedError,
)
from xonotic_webui.maps.control import (
    GametypeUnavailableError,
    MapNotInstalledError,
    UnknownGametypeError,
)
from xonotic_webui.runtime import Runtime
from xonotic_webui.serversettings.registry import ApplyClass
from xonotic_webui.supervisor import NotRunningError

FAST = "autopause_delay=0.2,endmatch_delay=0.05,scoreboard_delay=0.3"


@pytest.fixture
async def make_rt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Callable[..., Runtime]]:
    made: list[Runtime] = []

    def factory(flags: str = FAST, **overrides: object) -> Runtime:
        monkeypatch.setenv("FAKE_XONOTIC", flags)
        rt = Runtime(make_settings(tmp_path, **overrides))
        made.append(rt)
        return rt

    yield factory
    for rt in made:
        await rt.shutdown()


async def until(predicate: Callable[[], bool], timeout: float = 8.0, what: str = "") -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"not reached in time: {what}")
        await asyncio.sleep(0.02)


def raw_output(rt: Runtime) -> list[str]:
    return [ln.plain for ln in rt.console.buffer.snapshot() if ln.kind is LineKind.OUTPUT]


def commands(rt: Runtime) -> list[str]:
    return [ln.text for ln in rt.console.buffer.snapshot() if ln.kind is LineKind.COMMAND]


async def streamed_history(rt: Runtime) -> list[str]:
    """What a client connecting now would be sent."""
    seen: list[str] = []
    stream = rt.console.stream()
    try:
        async with asyncio.timeout(0.4):
            async for line in stream:
                seen.append(line.plain)
    except TimeoutError:
        pass
    finally:
        await stream.aclose()
    return seen


# --- 4.3 gametype ----------------------------------------------------------------------


async def test_only_gametypes_some_installed_map_supports_are_offered(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt()
    view = rt.map_control.gametypes()
    offered = {o.gametype.id for o in view.options if o.offered}
    expected = {g for gametypes in fake_maps().values() for g in gametypes}
    assert offered == expected
    assert len(view.options) == 20
    assert "ca" not in offered
    counts = {o.gametype.id: o.map_count for o in view.options}
    assert counts["ctf"] == 3  # catharsis, leave_em_behind, runningmanctf


async def test_selecting_an_unplayable_or_unknown_gametype_is_refused(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt()
    with pytest.raises(GametypeUnavailableError, match="Clan Arena"):
        await rt.map_control.select_gametype("ca")
    with pytest.raises(UnknownGametypeError):
        await rt.map_control.select_gametype("nosuch")
    assert not rt.settings.game_settings_file.exists()


async def test_gametype_changed_while_stopped_is_used_by_the_first_match(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt()
    assert await rt.map_control.select_gametype("tdm") is ApplyClass.NEXT_START
    cfg = rt.server_settings.render_config()
    assert "g_tdm 1" in cfg and "g_dm 0" in cfg
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().gametype == "tdm", what="tdm first match")
    assert rt.status.snapshot().map == "atelier"  # the stock first map also plays tdm


async def test_gametype_change_takes_effect_at_the_next_map(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt()
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().gametype == "dm", what="dm")
    assert await rt.map_control.select_gametype("tdm") is ApplyClass.NEXT_MAP
    assert "gametype tdm" in commands(rt)
    assert rt.status.snapshot().gametype == "dm"  # the current match continues
    assert rt.map_control.effective_gametype() == "tdm"
    await rt.console.submit_command("changelevel boil")
    await until(lambda: rt.status.snapshot().gametype == "tdm", what="tdm next map")
    assert rt.status.snapshot().map == "boil"


async def test_gametype_persists_across_a_restart(make_rt: Callable[..., Runtime]) -> None:
    rt = make_rt()
    await rt.supervisor.start()
    await rt.map_control.select_gametype("tdm")
    await rt.supervisor.restart()
    await until(lambda: rt.status.snapshot().gametype == "tdm", what="tdm after restart")


# --- 4.4 rotation ----------------------------------------------------------------------


async def test_rotation_validation_and_defaults(make_rt: Callable[..., Runtime]) -> None:
    rt = make_rt()
    view = rt.map_control.rotation()
    assert view.maps == [] and view.shuffle is None
    with pytest.raises(MapNotInstalledError, match="nosuch"):
        await rt.map_control.set_rotation(["stormkeep", "nosuch"], None)
    assert not rt.settings.game_settings_file.exists()
    assert await rt.map_control.set_rotation(["boil", "boil", "stormkeep"], False) is (
        ApplyClass.NEXT_START
    )
    assert [m.name for m in rt.map_control.rotation().maps] == ["boil", "stormkeep"]


async def test_a_fixed_rotation_is_played_in_order(make_rt: Callable[..., Runtime]) -> None:
    rt = make_rt()
    await rt.server_settings.patch({"sv_autopause": False})
    await rt.map_control.select_gametype("tdm")
    await rt.map_control.set_rotation(["stormkeep", "boil", "warfare"], False)
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map == "stormkeep", what="first map")
    played = []
    for _ in range(4):
        before = rt.status.match_count
        await rt.console.submit_command("endmatch")
        await until(lambda b=before: rt.status.match_count > b, what="next match")
        played.append(rt.status.snapshot().map)
    assert played == ["boil", "warfare", "stormkeep", "boil"]


async def test_default_rotation_is_every_map_for_the_gametype(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt()
    await rt.server_settings.patch({"sv_autopause": False})
    await rt.map_control.select_gametype("ons")
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().gametype == "ons", what="ons")
    seen = {rt.status.snapshot().map}
    for _ in range(4):
        before = rt.status.match_count
        await rt.console.submit_command("endmatch")
        await until(lambda b=before: rt.status.match_count > b, what="next match")
        seen.add(rt.status.snapshot().map)
    assert seen == {"geoplanetary", "go", "space-elevator", "vorix"}  # all and only ons maps


async def test_an_incompatible_map_is_flagged_and_not_played(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt()
    await rt.server_settings.patch({"sv_autopause": False})
    await rt.map_control.select_gametype("tdm")
    await rt.map_control.set_rotation(["stormkeep", "catharsis", "boil"], False)
    flags = {m.name: m.supported for m in rt.map_control.rotation().maps}
    assert flags == {"stormkeep": True, "catharsis": False, "boil": True}
    assert 'g_maplist "stormkeep boil"' in rt.server_settings.render_config()
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map == "stormkeep", what="first map")
    before = rt.status.match_count
    await rt.console.submit_command("endmatch")
    await until(lambda: rt.status.match_count > before, what="next match")
    assert rt.status.snapshot().map == "boil"  # catharsis was left out


async def test_rotation_is_shown_as_saved_not_as_the_game_reordered_it(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt()
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map is not None, what="map")
    # the game fills its own g_maplist when none is set...
    live = await rt.server_settings.live_values(["g_maplist"])
    assert live["g_maplist"]
    # ...but the panel shows nothing configured
    assert rt.map_control.rotation().maps == []
    await rt.map_control.set_rotation(["warfare", "boil"], True)
    assert [m.name for m in rt.map_control.rotation().maps] == ["warfare", "boil"]
    live = await rt.server_settings.live_values(["g_maplist", "g_maplist_shuffle"])
    assert live == {"g_maplist": "warfare boil", "g_maplist_shuffle": "1"}


# --- 5.1 actions -----------------------------------------------------------------------


async def test_actions_need_a_running_server(make_rt: Callable[..., Runtime]) -> None:
    rt = make_rt()
    for action in (rt.match_actions.skip, rt.match_actions.restart):
        with pytest.raises(NotRunningError):
            await action()
    with pytest.raises(NotRunningError):
        await rt.match_actions.goto("boil")
    assert rt.status.snapshot().action is None


async def test_go_to_map_rejects_unknown_and_unsupported_maps(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt()
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map is not None, what="map")
    with pytest.raises(ActionMapNotInstalledError, match="not installed"):
        await rt.match_actions.goto("nosuchmap")
    # catharsis is capture the flag only
    await rt.map_control.select_gametype("tdm")
    before = len(commands(rt))
    with pytest.raises(ActionMapGametypeError) as err:
        await rt.match_actions.goto("catharsis")
    assert str(err.value) == "catharsis does not support Team Deathmatch"
    assert not any(c.startswith("gotomap") for c in commands(rt)[before:])
    assert rt.status.snapshot().action is None  # nothing was started


async def test_go_to_map_refuses_a_package_the_game_has_not_loaded(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt()
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map is not None, what="map")
    write_pk3(rt.settings.userdir / "data" / "late.pk3", {"latemap": {"gametypes": ["dm"]}})
    before = len(commands(rt))
    with pytest.raises(MapNotLoadedError, match="restart the server") as err:
        await rt.match_actions.goto("latemap")
    assert err.value.code == "map_needs_restart"
    assert not any(c.startswith("gotomap") for c in commands(rt)[before:])
    assert rt.status.snapshot().action is None  # the current match is untouched

    # the check comes before the gametype one, and a loaded map still works
    action = await rt.match_actions.goto("warfare")
    await until(lambda: action.state == "done", what="goto done")


async def test_go_to_map_goes_straight_there_without_a_vote(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt()
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map is not None, what="map")
    action = await rt.match_actions.goto("warfare")
    assert (action.kind, action.map, action.state) == ("goto", "warfare", "pending")
    await until(lambda: action.state == "done", what="goto done")
    assert rt.status.snapshot().map == "warfare"
    assert "gotomap warfare" in commands(rt)


async def test_skip_moves_to_the_next_map_and_restart_replays_this_one(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt()
    await rt.server_settings.patch({"sv_autopause": False})
    await rt.map_control.set_rotation(["boil", "warfare"], False)
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map == "boil", what="boil")
    skip = await rt.match_actions.skip()
    await until(lambda: skip.state == "done", what="skip done")
    assert rt.status.snapshot().map == "warfare"

    count = rt.status.match_count
    restart = await rt.match_actions.restart()
    await until(lambda: restart.state == "done", what="restart done")
    assert rt.status.snapshot().map == "warfare"
    assert rt.status.match_count == count + 1


async def test_a_second_action_is_rejected_while_one_is_pending(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt("endmatch_delay=0.05,scoreboard_delay=1.0,autopause_delay=30")
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map is not None, what="map")
    await rt.console.submit_command("fake_join 1 1 127.0.0.1 Human")
    await until(lambda: rt.status.snapshot().human_count == 1, what="human")
    first = await rt.match_actions.skip()
    with pytest.raises(ActionInProgressError, match="in progress"):
        await rt.match_actions.goto("warfare")
    with pytest.raises(ActionInProgressError):
        await rt.match_actions.restart()
    await until(lambda: first.state == "done", what="skip done")
    again = await rt.match_actions.restart()  # free again
    assert again.id == first.id + 1


# --- 5.2 idle auto-pause ------------------------------------------------------------------


async def _wait_paused(rt: Runtime) -> None:
    """The fake pauses itself ``autopause_delay`` after a map loads; give it time."""
    await asyncio.sleep(0.5)


async def test_skip_on_an_auto_paused_empty_server_completes(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt()
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map is not None, what="map")
    await _wait_paused(rt)
    before = rt.status.match_count
    action = await rt.match_actions.skip()
    await until(lambda: action.state == "done", what="skip done")
    assert rt.status.match_count == before + 1
    # the pause toggle was sent once and answered "unpaused": the server ran the command
    replies = [line for line in raw_output(rt) if line.endswith("the game")]
    assert [r.rsplit(" ", 3)[-3] for r in replies] == ["unpaused"]


async def test_go_to_map_on_an_auto_paused_empty_server_completes(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt()
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map is not None, what="map")
    await _wait_paused(rt)
    action = await rt.match_actions.goto("warfare")
    await until(lambda: action.state == "done", what="goto done")
    assert rt.status.snapshot().map == "warfare"


async def test_an_empty_but_running_server_is_not_left_paused(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt()
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map is not None, what="map")
    # a player joins (unpausing it) and leaves: empty, but not paused
    await rt.console.submit_command("fake_join 1 1 127.0.0.1 Human")
    await until(lambda: rt.status.snapshot().human_count == 1, what="joined")
    await rt.console.submit_command("fake_part 1")
    await until(lambda: rt.status.snapshot().human_count == 0, what="left")
    action = await rt.match_actions.skip()
    await until(lambda: action.state == "done", what="skip done")
    # the probe paused the running server; the panel put it back at once
    replies = [line.rsplit(" ", 3)[-3] for line in raw_output(rt) if line.endswith("the game")]
    assert replies == ["paused", "unpaused"]


async def test_nothing_is_paused_or_unpaused_while_players_are_connected(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt()
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map is not None, what="map")
    await rt.console.submit_command("fake_join 1 1 127.0.0.1 Human")
    await until(lambda: rt.status.snapshot().human_count == 1, what="joined")
    action = await rt.match_actions.skip()
    await until(lambda: action.state == "done", what="skip done")
    assert not any("paused the game" in line for line in raw_output(rt))
    assert "pause" not in commands(rt)


async def test_pause_handling_stays_out_of_the_console_stream(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt()
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map is not None, what="map")
    await _wait_paused(rt)
    action = await rt.match_actions.skip()
    await until(lambda: action.state == "done", what="skip done")
    assert any("paused the game" in line for line in raw_output(rt))  # it did happen
    history = await streamed_history(rt)
    assert not any("paused the game" in line for line in history)  # but clients never see it
    assert "pause" not in commands(rt)
    assert "endmatch" in commands(rt)  # the action itself is visible, like any command


async def test_auto_pause_stays_enabled(make_rt: Callable[..., Runtime]) -> None:
    rt = make_rt()
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map is not None, what="map")
    await _wait_paused(rt)
    action = await rt.match_actions.skip()
    await until(lambda: action.state == "done", what="skip done")
    values = await rt.server_settings.live_values(["sv_autopause"])
    assert values == {"sv_autopause": "1"}
    assert not any("sv_autopause" in c for c in commands(rt))


# --- 5.3 outcome ------------------------------------------------------------------------


async def test_pending_and_done_are_published_to_every_client(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt()
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map is not None, what="map")
    await _wait_paused(rt)

    seen: list[dict | None] = []

    async def watch() -> None:
        async for snap in rt.status.stream():
            seen.append(snap.action)
            if snap.action is not None and snap.action["state"] == "done":
                return

    watcher = asyncio.create_task(watch())
    await asyncio.sleep(0.05)
    action = await rt.match_actions.skip()
    await asyncio.wait_for(watcher, 8)
    states = [(a["id"], a["kind"], a["state"]) for a in seen if a is not None]
    assert states[0] == (action.id, "skip", "pending")
    assert states[-1] == (action.id, "skip", "done")
    assert rt.status.snapshot().action == {
        "id": action.id,
        "kind": "skip",
        "map": None,
        "state": "done",
    }


async def test_an_action_with_no_match_start_times_out(make_rt: Callable[..., Runtime]) -> None:
    # without the event log no ``:gamestart:`` is ever seen, so nothing can complete it
    rt = make_rt("eventlog_off,endmatch_delay=0.05,autopause_delay=30,map_delay=0.1")
    rt.match_actions._timeout = 0.5
    await rt.supervisor.start()
    action = await rt.match_actions.skip()
    assert action.state == "pending"
    await until(lambda: action.state == "timed_out", what="timeout")
    assert rt.status.snapshot().action["state"] == "timed_out"  # type: ignore[index]
    # and a new action may be started
    second = await rt.match_actions.restart()
    assert second.id == action.id + 1


async def test_a_goto_waits_for_the_requested_map(make_rt: Callable[..., Runtime]) -> None:
    rt = make_rt()
    await rt.server_settings.patch({"sv_autopause": False})
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map is not None, what="map")
    action = await rt.match_actions.goto("warfare")
    # an unrelated match start (a console changelevel) must not complete the goto
    await rt.console.submit_command("fake_map dm elsewhere")
    await until(lambda: rt.status.snapshot().map in ("elsewhere", "warfare"), what="a start")
    await until(lambda: action.state == "done", what="goto done")
    assert rt.status.snapshot().map == "warfare"


async def test_stopping_the_server_clears_a_pending_action(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt("endmatch_delay=0.05,scoreboard_delay=5,autopause_delay=30")
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map is not None, what="map")
    await rt.console.submit_command("fake_join 1 1 127.0.0.1 Human")
    await until(lambda: rt.status.snapshot().human_count == 1, what="joined")
    await rt.match_actions.skip()
    assert rt.status.snapshot().action is not None
    await rt.supervisor.stop()
    assert rt.status.snapshot().action is None
    assert rt.match_actions.current is None


# --- scenarios that needed a test of their own (7.3) -----------------------------------


async def test_settings_survive_a_panel_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_XONOTIC", FAST)
    first = Runtime(make_settings(tmp_path))
    await first.server_settings.patch({"hostname": "LAN Party", "skill": 4})
    await first.map_control.select_gametype("tdm")
    await first.shutdown()

    # a new panel process over the same state directory
    second = Runtime(make_settings(tmp_path))
    try:
        states = {s.setting.key: s.value for s in await second.server_settings.view()}
        assert states["hostname"] == "LAN Party" and states["skill"] == 4
        assert second.map_control.effective_gametype() == "tdm"
        await second.supervisor.start()
        await until(lambda: second.status.snapshot().gametype == "tdm", what="tdm")
        assert await second.server_settings.live_values(["hostname"]) == {"hostname": "LAN Party"}
    finally:
        await second.shutdown()


async def test_goto_with_players_connected_ends_with_the_scoreboard_and_skips_the_vote(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt("endmatch_delay=0.05,scoreboard_delay=0.4,vote_delay=5,autopause_delay=30")
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map is not None, what="map")
    await rt.console.submit_command("fake_join 1 1 127.0.0.1 Human")
    await until(lambda: rt.status.snapshot().human_count == 1, what="joined")
    started = asyncio.get_running_loop().time()
    action = await rt.match_actions.goto("warfare")
    await until(lambda: action.state == "done", timeout=4.0, what="goto done")
    elapsed = asyncio.get_running_loop().time() - started
    assert 0.35 <= elapsed < 3.0  # the scoreboard was shown, the 5 s vote was not
    assert rt.status.snapshot().map == "warfare"
    assert any(line.startswith(":scores:") for line in raw_output(rt))


async def test_skip_with_players_goes_through_the_scoreboard_and_the_vote(
    make_rt: Callable[..., Runtime],
) -> None:
    rt = make_rt("endmatch_delay=0.05,scoreboard_delay=0.3,vote_delay=0.5,autopause_delay=30")
    await rt.supervisor.start()
    await until(lambda: rt.status.snapshot().map is not None, what="map")
    await rt.console.submit_command("fake_join 1 1 127.0.0.1 Human")
    await until(lambda: rt.status.snapshot().human_count == 1, what="joined")
    started = asyncio.get_running_loop().time()
    action = await rt.match_actions.skip()
    await until(lambda: action.state == "done", timeout=5.0, what="skip done")
    assert asyncio.get_running_loop().time() - started >= 0.75  # scoreboard + vote
