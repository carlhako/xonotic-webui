"""The match watcher wired into the runtime, against the fake dedicated server."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import make_settings
from xonotic_webui.runtime import Runtime
from xonotic_webui.supervisor import RunState


@pytest.fixture
async def runtimes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Callable[..., Any]]:
    created: list[Runtime] = []

    async def make(spec: str = "", *, run: bool = True, **settings: Any) -> Runtime:
        monkeypatch.setenv("FAKE_XONOTIC", spec)
        rt = Runtime(make_settings(tmp_path, readiness_timeout=20, **settings))
        await rt.startup()
        created.append(rt)
        if run:
            await rt.supervisor.start()
        return rt

    yield make
    for rt in created:
        await rt.shutdown()


async def until(predicate: Callable[[], Any], timeout: float = 8.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        value = predicate()
        if asyncio.iscoroutine(value):
            value = await value
        if value:
            return
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


class Watch:
    """Subscribes to the watcher's stream in the background and records its events."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self.events: list[dict] = []
        self._task: asyncio.Task | None = None

    def __enter__(self) -> Watch:
        self._task = asyncio.get_running_loop().create_task(self._pump())
        return self

    async def _pump(self) -> None:
        async for snap in self.rt.match.stream():
            self.events.append(snap)

    def __exit__(self, *exc: object) -> None:
        assert self._task is not None
        self._task.cancel()

    async def close(self) -> None:
        assert self._task is not None
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)


async def send(rt: Runtime, *commands: str) -> None:
    for command in commands:
        await rt.supervisor.send_command(command)


async def test_no_queries_without_subscribers(runtimes: Any) -> None:
    rt = await runtimes()
    await asyncio.sleep(1.5)
    assert rt.match.subscriber_count == 0 and not rt.match.polling
    assert rt.match.snapshot()["live"] is False
    # the server was sent nothing: not one of the poll's replies is in its output at all
    assert not any("game_starttime" in ln.plain for ln in rt.supervisor.console.snapshot())


async def test_polling_starts_with_the_first_subscriber_and_stops_with_the_last(
    runtimes: Any,
) -> None:
    rt = await runtimes()
    first = Watch(rt)
    with first:
        await until(lambda: rt.match.polling and first.events and first.events[-1]["live"])
        second = Watch(rt)
        with second:
            await until(lambda: rt.match.subscriber_count == 2)
            await second.close()
        await until(lambda: rt.match.subscriber_count == 1)
        assert rt.match.polling
        await first.close()
    await until(lambda: rt.match.subscriber_count == 0)
    assert not rt.match.polling


async def test_no_polls_are_sent_after_the_last_subscriber_leaves(runtimes: Any) -> None:
    rt = await runtimes()
    watch = Watch(rt)
    with watch:
        await until(lambda: len(watch.events) >= 1 and watch.events[-1]["live"])
        await watch.close()
    await until(lambda: not rt.match.polling)
    marker = len(rt.supervisor.console.snapshot())
    seen_before = rt.supervisor.console.snapshot()[-1].seq
    await asyncio.sleep(1.6)
    assert rt.supervisor.console.snapshot()[-1].seq == seen_before
    assert marker == len(rt.supervisor.console.snapshot())


async def test_a_live_snapshot_has_the_clock_limits_and_scoreboard(runtimes: Any) -> None:
    rt = await runtimes()
    await send(
        rt,
        "fake_join 1 1 127.0.0.1 ^1Red^7Name",
        "fake_join 2 2 bot [BOT]Eureka",
        "fake_score 1 score=5 kills=5",
        "fake_clock 216",  # 3:20 after a start at 16
    )
    watch = Watch(rt)
    with watch:
        await until(
            lambda: (
                watch.events
                and watch.events[-1]["scoreboard"]["available"]
                and watch.events[-1]["scoreboard"]["players"]
            )
        )
        snap = watch.events[-1]
        await watch.close()
    assert snap["live"] is True
    assert snap["gametype"] == "dm"
    clock = snap["clock"]
    assert clock["available"] and clock["phase"] == "playing" and not clock["paused"]
    assert clock["time_limit_s"] is not None
    assert clock["elapsed_s"] >= 200
    assert snap["score_limit"] == {"value": 30, "unit": "frags"}
    players = snap["scoreboard"]["players"]
    assert [(p["plain_name"], p["bot"], p["values"]["score"]) for p in players] == [
        ("RedName", False, 5),
        ("[BOT]Eureka", True, 0),
    ]


async def test_a_paused_server_is_reported_paused_and_pushes_nothing(runtimes: Any) -> None:
    rt = await runtimes("autopause_delay=0.3")
    watch = Watch(rt)
    with watch:
        await until(lambda: any(e["clock"]["paused"] for e in watch.events), timeout=10)
        paused_at = len(watch.events)
        frozen = watch.events[-1]["clock"]
        await asyncio.sleep(2.2)  # two more reads of an unchanged server
        assert len(watch.events) == paused_at
        assert watch.events[-1]["clock"] == frozen
        await watch.close()


async def test_resuming_clears_paused(runtimes: Any) -> None:
    rt = await runtimes("autopause_delay=0.3")
    watch = Watch(rt)
    with watch:
        await until(lambda: any(e["clock"]["paused"] for e in watch.events), timeout=10)
        await send(rt, "fake_join 1 1 127.0.0.1 Human")  # the first human unpauses it
        await until(lambda: not watch.events[-1]["clock"]["paused"])
        await watch.close()


async def test_the_scoreboard_is_unavailable_without_a_dump_while_the_clock_shows(
    runtimes: Any,
) -> None:
    rt = await runtimes("no_dump")
    watch = Watch(rt)
    with watch:
        await until(lambda: watch.events and watch.events[-1]["live"])
        snap = watch.events[-1]
        await watch.close()
    assert snap["scoreboard"]["available"] is False
    assert snap["clock"]["available"] is True


async def test_the_clock_is_unavailable_without_the_globals_while_the_scoreboard_shows(
    runtimes: Any,
) -> None:
    rt = await runtimes("unknown_globals=time+game_starttime")
    await send(rt, "fake_join 1 1 127.0.0.1 Human")
    watch = Watch(rt)
    with watch:
        await until(
            lambda: (
                watch.events
                and watch.events[-1]["live"]
                and watch.events[-1]["scoreboard"]["players"]
            )
        )
        snap = watch.events[-1]
        await watch.close()
    assert snap["clock"]["available"] is False
    assert snap["scoreboard"]["available"] is True
    # the game's error lines for the unknown globals are not in the console
    assert [ln.plain async for ln in _replay(rt) if "No global" in ln.plain] == []


async def test_stopping_the_server_publishes_not_live_and_polling_stops(runtimes: Any) -> None:
    rt = await runtimes()
    watch = Watch(rt)
    with watch:
        await until(lambda: watch.events and watch.events[-1]["live"])
        await rt.supervisor.stop()
        await until(lambda: watch.events[-1]["live"] is False)
        assert not rt.match.polling
        last = watch.events[-1]
        assert last["map"] is None
        assert last["clock"]["available"] is False
        assert last["scoreboard"]["available"] is False
        await watch.close()


async def test_polling_resumes_when_the_server_runs_again(runtimes: Any) -> None:
    rt = await runtimes()
    watch = Watch(rt)
    with watch:
        await until(lambda: watch.events and watch.events[-1]["live"])
        await rt.supervisor.stop()
        await until(lambda: watch.events[-1]["live"] is False)
        await rt.supervisor.start()
        await until(lambda: watch.events[-1]["live"] is True, timeout=15)
        await watch.close()


async def test_a_subscriber_while_stopped_gets_not_live_and_no_error(runtimes: Any) -> None:
    rt = await runtimes(run=False)
    assert rt.supervisor.state is RunState.STOPPED
    watch = Watch(rt)
    with watch:
        await until(lambda: watch.events)
        assert watch.events[0]["live"] is False
        assert not rt.match.polling
        await watch.close()


async def test_an_unanswered_poll_keeps_the_last_snapshot(runtimes: Any) -> None:
    rt = await runtimes()
    watch = Watch(rt)
    with watch:
        await until(lambda: watch.events and watch.events[-1]["live"])
        good = watch.events[-1]
        # make every later poll unanswerable: it is not a command the fake would reply to
        original = rt.console.query

        async def silent(command: str, collector: Any, **kw: Any) -> Any:
            if "printstats" in command:
                from xonotic_webui.console.console import InternalQueryError

                raise InternalQueryError("no reply")
            return await original(command, collector, **kw)

        rt.console.query = silent  # type: ignore[method-assign]
        n = len(watch.events)
        await asyncio.sleep(1.5)
        assert len(watch.events) == n
        assert rt.match.snapshot() == good
        assert rt.match.polling
        await watch.close()


# --- 4.2 the console stays clean ----------------------------------------------------------


async def test_the_poll_never_reaches_a_console_client_or_the_replay(runtimes: Any) -> None:
    rt = await runtimes()
    received: list[str] = []

    async def console_client() -> None:
        async for line in rt.console.stream():
            received.append(line.plain)

    client = asyncio.get_running_loop().create_task(console_client())
    watch = Watch(rt)
    with watch:
        await until(lambda: len(watch.events) >= 1 and watch.events[-1]["live"])
        await asyncio.sleep(3.2)  # a few ticks
        await watch.close()
    client.cancel()
    await asyncio.gather(client, return_exceptions=True)

    banned = ("game_starttime", "time: ", "stats dumped", ":status:", "see-labels", "logscores")
    leaked = [ln for ln in received if any(b in ln for b in banned)]
    assert leaked == []
    replay = [line.plain async for line in _replay(rt)]
    assert [ln for ln in replay if any(b in ln for b in banned)] == []


async def _replay(rt: Runtime) -> AsyncIterator[Any]:
    from contextlib import aclosing

    count = len(rt.supervisor.console.snapshot())
    async with aclosing(rt.console.stream()) as source:
        for _ in range(count):
            try:
                yield await asyncio.wait_for(anext(source), 0.5)
            except (TimeoutError, StopAsyncIteration):
                return


async def test_a_status_reconcile_during_a_tick_gets_its_own_reply(runtimes: Any) -> None:
    from xonotic_webui.events import StatusReplyCollector

    rt = await runtimes()
    await send(rt, "fake_join 1 1 127.0.0.1 Human", "fake_join 2 2 bot [BOT]x")
    watch = Watch(rt)
    with watch:
        await until(lambda: len(watch.events) >= 1 and watch.events[-1]["live"])
        for _ in range(8):
            replies = await asyncio.gather(
                *(
                    rt.console.query("status 1", StatusReplyCollector(), reply_timeout=5)
                    for _ in range(2)
                )
            )
            for collector in replies:
                assert [(r.ent, r.bot) for r in collector.rows] == [(1, False), (2, True)]
            await asyncio.sleep(0.15)
        await watch.close()
    assert [ln.plain async for ln in _replay(rt) if "botclient" in ln.plain] == []
