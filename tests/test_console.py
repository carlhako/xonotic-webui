"""Console fan-out, replay, commands and queries (server-console spec)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

from tests.helpers import make_settings
from xonotic_webui.console import ConsoleBuffer, ConsoleLine, LineKind
from xonotic_webui.console.console import (
    Console,
    InternalQueryError,
    InvalidCommandError,
    validate_command,
)
from xonotic_webui.events import StatusReplyCollector
from xonotic_webui.settings import Settings
from xonotic_webui.supervisor import NotRunningError, Supervisor


@pytest.fixture
async def started(tmp_path: Path) -> AsyncIterator[tuple[Supervisor, Console]]:
    settings: Settings = make_settings(tmp_path)
    sup = Supervisor(settings)
    console = Console(sup)
    await sup.start()
    yield sup, console
    await sup.aclose()


async def take(
    stream: AsyncIterator[ConsoleLine], n: int, timeout: float = 5.0
) -> list[ConsoleLine]:
    out: list[ConsoleLine] = []
    for _ in range(n):
        out.append(await asyncio.wait_for(anext(stream), timeout))
    return out


async def next_matching(
    stream: AsyncIterator[ConsoleLine],
    predicate: Callable[[ConsoleLine], bool],
    timeout: float = 5.0,
) -> ConsoleLine:
    async def go() -> ConsoleLine:
        async for line in stream:
            if predicate(line):
                return line
        raise AssertionError("stream ended")

    return await asyncio.wait_for(go(), timeout)


# --- buffer -----------------------------------------------------------------


def test_buffer_is_bounded_and_discards_oldest_first() -> None:
    buf = ConsoleBuffer(3)
    for i in range(10):
        buf.add_output(f"line {i}")
    assert len(buf) == 3
    assert [line.text for line in buf.snapshot()] == ["line 7", "line 8", "line 9"]
    assert buf.maxlen == 3


def test_buffer_sequence_is_monotonic_and_snapshot_can_resume() -> None:
    buf = ConsoleBuffer(10)
    a = buf.add_output("a")
    b = buf.add_command("b")
    c = buf.add_marker("c")
    assert (a.seq, b.seq, c.seq) == (1, 2, 3)
    assert [line.kind for line in buf.snapshot(after_seq=1)] == [LineKind.COMMAND, LineKind.MARKER]
    assert buf.last_seq() == 3


def test_buffer_exposes_the_colour_stripped_form() -> None:
    buf = ConsoleBuffer(10)
    line = buf.add_output("^7:join:1:1:bot:^1Red^xf80Orange^7 Pl:ay^^er")
    assert line.text.startswith("^7:join")  # raw retained for display
    assert line.plain == ":join:1:1:bot:RedOrange Pl:ay^er"


def test_a_raising_listener_does_not_corrupt_the_buffer() -> None:
    buf = ConsoleBuffer(10)
    buf.add_listener(lambda _l: 1 / 0)
    seen: list[str] = []
    buf.add_listener(lambda line: seen.append(line.text))
    buf.add_output("still works")
    assert seen == ["still works"]
    assert len(buf) == 1


# --- fan-out and replay ------------------------------------------------------


async def test_output_is_streamed_in_order_to_every_client(
    started: tuple[Supervisor, Console],
) -> None:
    sup, console = started
    a, b = console.stream(), console.stream()
    # drain the history both clients start with
    history = len(console.buffer)
    await take(a, history)
    await take(b, history)

    await sup.send_command("fake_emit ^7first")
    await sup.send_command("fake_emit ^7second")

    la = await next_matching(a, lambda line: line.plain == "first")
    lb = await next_matching(b, lambda line: line.plain == "first")
    assert la.seq == lb.seq
    assert (await next_matching(a, lambda line: line.plain == "second")).seq > la.seq
    assert (await next_matching(b, lambda line: line.plain == "second")).seq > lb.seq
    assert console.subscriber_count == 2
    await a.aclose()
    await b.aclose()
    assert console.subscriber_count == 0


async def test_connect_mid_session_replays_history_then_live_without_duplicates(
    started: tuple[Supervisor, Console],
) -> None:
    sup, console = started
    for i in range(5):
        await sup.send_command(f"fake_emit ^7before {i}")
    await asyncio.sleep(0.2)

    stream = console.stream()
    for i in range(5):
        await sup.send_command(f"fake_emit ^7after {i}")

    seqs: list[int] = []
    texts: list[str] = []
    async for line in stream:
        seqs.append(line.seq)
        texts.append(line.plain)
        if line.plain == "after 4":
            break
    await stream.aclose()

    assert seqs == sorted(set(seqs)), "no line delivered twice, none out of order"
    assert "before 0" in texts and texts.index("before 4") < texts.index("after 0")
    assert texts[0].startswith("Game is Xonotic")  # buffered startup came first


async def test_stream_does_not_fail_when_server_is_stopped(tmp_path: Path) -> None:
    sup = Supervisor(make_settings(tmp_path))
    console = Console(sup)
    stream = console.stream()
    task = asyncio.create_task(anext(stream))
    await asyncio.sleep(0.1)
    assert not task.done()  # waiting, not erroring
    sup.console.add_output("hello")
    assert (await asyncio.wait_for(task, 2)).text == "hello"
    await stream.aclose()


# --- commands --------------------------------------------------------------------


async def test_command_is_delivered_and_its_output_streamed(
    started: tuple[Supervisor, Console],
) -> None:
    _, console = started
    stream = console.stream()
    await console.submit_command("fake_emit ^7pong")
    cmd = await next_matching(stream, lambda line: line.kind is LineKind.COMMAND)
    assert cmd.text == "fake_emit ^7pong"  # echoed
    await next_matching(stream, lambda line: line.plain == "pong")
    await stream.aclose()


async def test_command_while_stopped_is_rejected_and_not_queued(tmp_path: Path) -> None:
    sup = Supervisor(make_settings(tmp_path))
    console = Console(sup)
    before = len(sup.console)
    with pytest.raises(NotRunningError, match="not running"):
        await console.submit_command("status 1")
    assert len(sup.console) == before  # not echoed, not queued


@pytest.mark.parametrize("bad", ["", "   ", "\t", "a\nb", "status\r\nquit", "x\n"])
async def test_empty_or_multiline_command_is_rejected_and_nothing_is_sent(
    started: tuple[Supervisor, Console], bad: str
) -> None:
    _, console = started
    before = console.buffer.last_seq()
    with pytest.raises(InvalidCommandError):
        await console.submit_command(bad)
    assert console.buffer.last_seq() == before


def test_validate_command_trims_and_bounds() -> None:
    assert validate_command("  status 1  ") == "status 1"
    with pytest.raises(InvalidCommandError):
        validate_command("x" * 5000)


# --- queries -----------------------------------------------------------------------


async def test_query_returns_the_reply_and_withholds_it_from_clients(
    started: tuple[Supervisor, Console],
) -> None:
    sup, console = started
    stream = console.stream()
    await take(stream, len(console.buffer))

    reply = await console.query_line(
        "sv_eventlog", lambda plain: plain.startswith('"sv_eventlog" is')
    )
    assert '"sv_eventlog" is "1"' in reply

    # an ordinary line after the query reaches the client; the reply and the command
    # that asked for it never did
    await sup.send_command("fake_emit ^7marker-after-query")
    seen: list[ConsoleLine] = []

    async def collect() -> None:
        async for line in stream:
            seen.append(line)
            if line.plain == "marker-after-query":
                return

    await asyncio.wait_for(collect(), 5)
    assert all('"sv_eventlog" is' not in line.plain for line in seen)
    assert all(line.kind is not LineKind.COMMAND for line in seen)
    await stream.aclose()

    # and a client connecting later does not see it in replayed history either
    fresh = console.stream()
    replay = await take(fresh, len(console.buffer) - 1)
    await fresh.aclose()
    assert all('"sv_eventlog" is' not in line.plain for line in replay)


async def test_query_timeout_raises_and_leaves_things_untouched(
    started: tuple[Supervisor, Console],
) -> None:
    sup, console = started
    with pytest.raises(InternalQueryError):
        await console.query_line("status 1", lambda plain: plain == "never", reply_timeout=0.3)
    assert sup.state.value == "running"
    # the collector was unregistered: a later matching line is not swallowed
    stream = console.stream()
    await take(stream, len(console.buffer))
    await sup.send_command("fake_emit ^7never")
    assert (await next_matching(stream, lambda line: line.plain == "never")).plain == "never"
    await stream.aclose()


async def test_query_while_stopped_is_not_queued(tmp_path: Path) -> None:
    sup = Supervisor(make_settings(tmp_path))
    console = Console(sup)
    with pytest.raises(NotRunningError):
        await console.query_line("status 1", lambda plain: True, reply_timeout=0.2)
    assert len(sup.console) == 0


async def test_multi_line_query_collects_a_status_reply(
    started: tuple[Supervisor, Console],
) -> None:
    sup, console = started
    await sup.send_command("fake_join 1 1 127.0.0.1 ^1Red^7Name")
    await sup.send_command("fake_join 2 2 bot [BOT]Toxic")
    collector = await console.query("status 1", StatusReplyCollector())
    assert collector.map == "atelier"
    assert [(r.ent, r.bot) for r in collector.rows] == [(1, False), (2, True)]
