"""Status tracking: fixture-driven parsing, reconciliation, staleness and streaming."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

from tests.helpers import make_settings
from xonotic_webui.console.console import Console
from xonotic_webui.settings import Settings
from xonotic_webui.status import StatusSnapshot, StatusTracker
from xonotic_webui.supervisor import RunState, Supervisor

FIXTURES = Path(__file__).parent / "fixtures" / "xonotic"


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    monkeypatch.delenv("FAKE_XONOTIC", raising=False)

    def apply(spec: str) -> None:
        monkeypatch.setenv("FAKE_XONOTIC", spec)

    return apply


class Stack:
    def __init__(self, settings: Settings, **tracker_kwargs: object) -> None:
        self.settings = settings
        self.sup = Supervisor(settings, probe_after=0.3, probe_interval=0.2)
        self.console = Console(self.sup)
        self.tracker = StatusTracker(self.sup, self.console, **tracker_kwargs)  # type: ignore[arg-type]

    async def close(self) -> None:
        await self.tracker.aclose()
        await self.sup.aclose()


@pytest.fixture
async def make_stack(tmp_path: Path) -> AsyncIterator[Callable[..., Stack]]:
    stacks: list[Stack] = []

    def factory(**overrides: object) -> Stack:
        tracker_kwargs = {
            k: overrides.pop(k) for k in ("query_timeout", "poll_interval") if k in overrides
        }
        stack = Stack(make_settings(tmp_path, **overrides), **tracker_kwargs)
        stacks.append(stack)
        return stack

    yield factory
    for stack in stacks:
        await stack.close()


async def wait_for(predicate: Callable[[], bool], timeout: float = 8.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


def feed(stack: Stack, name: str, *, until: str | None = None) -> None:
    for line in (FIXTURES / name).read_text().splitlines():
        stack.tracker.on_line(line)
        if until is not None and until in line:
            return


def names(snap: StatusSnapshot) -> list[tuple[str, bool]]:
    return [(p.to_dict()["plain_name"], p.bot) for p in snap.players]


# --- 6.1 event-driven model, real captures ----------------------------------------


async def test_matches_players_and_bots_from_a_real_session(
    make_stack: Callable[..., Stack],
) -> None:
    stack = make_stack()
    feed(stack, "session_humans_bots_v6.txt", until=":join:2:3:bot:[BOT]Resurrection")
    snap = stack.tracker.snapshot()
    assert snap.map == "atelier"
    assert snap.gametype == "dm"
    assert snap.human_count == 1
    assert snap.bot_count == 1
    assert {p.name for p in snap.players if not p.bot} == {"^1Red^xf80Orange^7 Pl:ay^^er"}


async def test_rename_part_and_next_match_from_a_real_session(
    make_stack: Callable[..., Stack],
) -> None:
    stack = make_stack()
    feed(stack, "session_humans_bots_v6.txt", until='Client "V6 ^4Blue^7" dropped')
    snap = stack.tracker.snapshot()
    # the first human was renamed then left; the IPv6 human is still here
    assert sorted(names(snap)) == [("V6 Blue", False), ("[BOT]Resurrection", True)]

    feed(stack, "match_end_next_map.txt")
    snap = stack.tracker.snapshot()
    assert (snap.map, snap.gametype) == ("boil", "dm")


async def test_three_humans_and_two_bots_are_counted_separately(
    make_stack: Callable[..., Stack],
) -> None:
    stack = make_stack()
    for i, name in enumerate(["A", "B", "C"], start=1):
        stack.tracker.on_line(f"^7:join:{i}:{i}:127.0.0.1:{name}")
    for i, name in enumerate(["[BOT]X", "[BOT]Y"], start=4):
        stack.tracker.on_line(f"^7:join:{i}:{i}:bot:{name}")
    snap = stack.tracker.snapshot()
    assert len(snap.players) == 5
    assert (snap.human_count, snap.bot_count) == (3, 2)
    d = snap.to_dict()
    assert (d["human_count"], d["bot_count"]) == (3, 2)


async def test_player_leaves_and_name_changes(make_stack: Callable[..., Stack]) -> None:
    stack = make_stack()
    stack.tracker.on_line("^7:join:1:1:127.0.0.1:^1Old^7")
    stack.tracker.on_line("^7:name:1:^2New^7")
    assert names(stack.tracker.snapshot()) == [("New", False)]
    stack.tracker.on_line("^7:part:1")
    assert stack.tracker.snapshot().players == ()


async def test_unknown_map_and_gametype_are_not_guessed(
    make_stack: Callable[..., Stack],
) -> None:
    stack = make_stack()
    snap = stack.tracker.snapshot()
    assert snap.map is None and snap.gametype is None


# --- 6.2 reconcile ----------------------------------------------------------------------


async def test_ready_reconciles_the_roster_and_confirms_the_event_log(
    make_stack: Callable[..., Stack],
) -> None:
    stack = make_stack()
    await stack.sup.start()
    await wait_for(lambda: stack.tracker.snapshot().event_log == "enabled")
    assert stack.tracker.snapshot().map == "atelier"


async def test_missed_events_are_recovered_by_a_status_query(
    make_stack: Callable[..., Stack],
) -> None:
    stack = make_stack()
    await stack.sup.start()
    await wait_for(lambda: stack.tracker.snapshot().event_log == "enabled")

    # Two players the event log never told us about, then a part for an unknown id.
    await stack.sup.send_command("fake_silent_join 5 127.0.0.1 ^1Ghost^7")
    await stack.sup.send_command("fake_silent_join 6 bot [BOT]Phantom")
    assert stack.tracker.snapshot().players == ()
    await stack.sup.send_command("fake_part 99")  # a gap: nobody we know of

    await wait_for(lambda: len(stack.tracker.snapshot().players) == 2)
    snap = stack.tracker.snapshot()
    assert sorted(names(snap)) == [("Ghost", False), ("[BOT]Phantom", True)]
    assert snap.human_count == 1 and snap.bot_count == 1


# --- 6.3 event log unavailable --------------------------------------------------------------


async def test_event_log_unavailable_is_reported_not_an_empty_roster(
    make_stack: Callable[..., Stack], fake: Callable[[str], None]
) -> None:
    fake("eventlog_off,map_delay=0.1")
    stack = make_stack(poll_interval=0.2)
    await stack.sup.start()
    await wait_for(lambda: stack.tracker.snapshot().event_log == "unavailable")
    snap = stack.tracker.snapshot()
    assert snap.to_dict()["event_log"] == "unavailable"
    assert snap.map == "atelier"  # still learnt from status

    # With no events the roster is still kept honest by polling.
    await stack.sup.send_command("fake_silent_join 7 127.0.0.1 Polled")
    await wait_for(lambda: len(stack.tracker.snapshot().players) == 1)
    assert names(stack.tracker.snapshot()) == [("Polled", False)]


# --- 6.4 not stale ----------------------------------------------------------------------------


async def test_crash_with_players_connected_clears_them_and_records_the_crash(
    make_stack: Callable[..., Stack],
) -> None:
    stack = make_stack(crash_restart_threshold=0)
    await stack.sup.start()
    await wait_for(lambda: stack.tracker.snapshot().event_log == "enabled")
    await stack.sup.send_command("fake_join 1 1 127.0.0.1 ^1Red^7")
    await wait_for(lambda: len(stack.tracker.snapshot().players) == 1)

    await stack.sup.send_command("fake_crash")
    await wait_for(lambda: stack.sup.state is RunState.STOPPED)

    snap = stack.tracker.snapshot()
    assert snap.players == ()
    assert snap.map is None and snap.gametype is None
    assert snap.last_crash is not None and snap.last_crash["exit_code"] == 139


async def test_stopped_server_has_no_map_gametype_or_players(
    make_stack: Callable[..., Stack],
) -> None:
    stack = make_stack()
    await stack.sup.start()
    await wait_for(lambda: stack.tracker.snapshot().map == "atelier")
    await stack.sup.stop()
    snap = stack.tracker.snapshot()
    assert snap.state == "stopped"
    assert (snap.map, snap.gametype, snap.players) == (None, None, ())
    assert snap.last_crash is None  # a requested stop is not a crash


async def test_restart_abandoned_and_last_crash_are_visible(
    make_stack: Callable[..., Stack], fake: Callable[[str], None]
) -> None:
    fake("crash_after=0.05")
    stack = make_stack(crash_restart_threshold=1, crash_restart_window=60.0)
    await stack.sup.start()
    await wait_for(lambda: stack.tracker.snapshot().restart_abandoned, timeout=15)
    d = stack.tracker.snapshot().to_dict()
    assert d["restart_abandoned"] is True
    assert d["last_crash"]["exit_code"] == 139
    assert d["state"] == "stopped"


# --- 6.5 snapshot and stream -------------------------------------------------------------------


async def test_stream_sends_the_snapshot_on_connect_then_every_change(
    make_stack: Callable[..., Stack],
) -> None:
    stack = make_stack()
    stream = stack.tracker.stream()
    first = await asyncio.wait_for(anext(stream), 2)
    assert first.state == "stopped"

    start = asyncio.create_task(stack.sup.start())
    seen: list[str] = []

    async def until_running() -> None:
        async for snap in stream:
            seen.append(snap.state)
            if snap.state == "running":
                return

    await asyncio.wait_for(until_running(), 8)
    await start
    assert "starting" in seen or seen == ["running"]  # latest-wins may collapse updates

    await stack.sup.send_command("fake_join 1 1 127.0.0.1 ^1Red^7")

    async def until_player() -> StatusSnapshot:
        async for snap in stream:
            if snap.players:
                return snap
        raise AssertionError

    snap = await asyncio.wait_for(until_player(), 5)
    assert names(snap) == [("Red", False)]
    await stream.aclose()
    assert stack.tracker.subscriber_count == 0


async def test_every_connected_client_gets_updates(make_stack: Callable[..., Stack]) -> None:
    stack = make_stack()
    await stack.sup.start()
    await wait_for(lambda: stack.tracker.snapshot().event_log == "enabled")
    a, b = stack.tracker.stream(), stack.tracker.stream()
    await asyncio.wait_for(anext(a), 2)
    await asyncio.wait_for(anext(b), 2)

    await stack.sup.send_command("fake_join 1 1 127.0.0.1 Someone")

    async def has_player(stream: AsyncIterator[StatusSnapshot]) -> StatusSnapshot:
        async for snap in stream:
            if snap.players:
                return snap
        raise AssertionError

    sa, sb = await asyncio.wait_for(asyncio.gather(has_player(a), has_player(b)), 5)
    assert names(sa) == names(sb) == [("Someone", False)]
    await a.aclose()
    await b.aclose()


async def test_identical_snapshots_are_not_resent(make_stack: Callable[..., Stack]) -> None:
    stack = make_stack()
    stream = stack.tracker.stream()
    await asyncio.wait_for(anext(stream), 2)
    stack.tracker.on_line("^7:gamestart:dm_atelier:0.1.1")
    changed = await asyncio.wait_for(anext(stream), 2)
    assert changed.map == "atelier"
    stack.tracker.on_line("^7:gamestart:dm_atelier:0.1.2")  # same map and gametype again
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(stream), 0.3)
    await stream.aclose()
