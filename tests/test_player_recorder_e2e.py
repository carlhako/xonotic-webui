"""The recorder wired into the runtime, against the fake dedicated server."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import make_settings
from xonotic_webui.console.buffer import LineKind
from xonotic_webui.runtime import Runtime
from xonotic_webui.supervisor import RunState

FP = "dRXbACYQr56HZ6KBw0zOIi7K1hQ3sUdDvO+DxBuUlSA="


@pytest.fixture
async def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Runtime]:
    monkeypatch.delenv("FAKE_XONOTIC", raising=False)
    rt = Runtime(make_settings(tmp_path, readiness_timeout=20))
    await rt.startup()
    await rt.supervisor.start()
    yield rt
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
        await asyncio.sleep(0.05)


def current_match_id(rt: Runtime) -> str:
    for line in reversed(rt.supervisor.console.snapshot()):
        m = re.search(r":gamestart:\w+_\w+:(\S+)", line.plain)
        if m:
            return m.group(1)
    raise AssertionError("no :gamestart: seen")


def write_report(tmp_path: Path, match_id: str, *, finished: bool) -> Path:
    lines = [
        "^7V 9",
        "^7R xonotic-v0.8.6",
        "^7G dm",
        "^7M atelier",
        f"^7I {match_id}",
        "^7S fake",
        "^7D 120.5",
        f"^7P {FP}",
        "^7i 1",
        "^7n ^1Tester",
        "^7r 1",
        "^7e scoreboard-score 7",
        "^7e total-score 7",
        "^7e acc-vortex-fired 200",
        "^7e acc-vortex-hit 100",
        "^7e alivetime 100.5",
        "^7e scoreboardvalid 1",
        "^7e joins 1",
    ]
    if finished:
        lines += ["^7e matches 1", "^7e wins 1"]
    lines += [
        "^7P bot#3#Eureka",
        "^7i 2",
        "^7n [BOT]Eureka",
        "^7e alivetime 90",
        "^7",
    ]
    path = tmp_path / "report.txt"
    path.write_text("\n".join(lines) + "\n")
    return path


async def test_the_runtime_wires_the_recorder_and_the_report_filter(runtime: Runtime) -> None:
    assert runtime.recorder.enabled
    assert runtime.recorder.store is runtime.players_store
    assert runtime.players_store.path == runtime.settings.players_db
    assert runtime.settings.players_db.is_file()


async def test_join_kills_report_and_stop_end_up_in_the_store(
    runtime: Runtime, tmp_path: Path
) -> None:
    sup = runtime.supervisor
    await sup.send_command(f"fake_join 1 1 127.0.0.1 fp={FP} ^1Tester")
    await sup.send_command("fake_join 2 2 bot [BOT]Eureka")
    await until(lambda: runtime.recorder.store.is_open)
    await sup.send_command("fake_kill frag 1 2")
    await sup.send_command("fake_kill frag 1 2")
    await sup.send_command("fake_kill suicide 1 1 KILL")
    report = write_report(tmp_path, current_match_id(runtime), finished=True)
    await sup.send_command("fake_emit ^7:end")
    await sup.send_command(f"fake_report {report}")
    await sup.send_command("fake_emit ^7:gameover")

    async def human_row() -> bool:
        total, rows = await runtime.players_store.list_players()
        return total == 1 and rows[0]["frags"] == 2 and rows[0]["wins"] == 1

    await until(human_row)
    _, rows = await runtime.players_store.list_players()
    row = rows[0]
    assert row["name"] == "^1Tester"
    assert (row["frags"], row["deaths"], row["suicides"]) == (2, 1, 1)
    assert row["score"] == 7 and row["matches"] == 1 and row["time_playing"] == 100.5
    assert row["accuracy"] == pytest.approx(0.5)

    # the report is for the recorder, not the Console tab
    texts = [
        line.plain for line in runtime.console.buffer.snapshot() if line.kind is LineKind.OUTPUT
    ]
    assert ":end" in texts and ":gameover" in texts and "V 9" in texts  # still in the buffer
    stream = runtime.console.stream()
    delivered: list[str] = []

    async def collect() -> None:
        async for line in stream:
            delivered.append(line.plain)
            if line.plain == ":gameover":
                return

    await asyncio.wait_for(collect(), 5)
    await stream.aclose()
    assert not any(t.startswith(("V ", "P ", "e ")) for t in delivered)

    # stopping the server ends the session at that moment
    await sup.stop()
    await until(lambda: sup.state is RunState.STOPPED)

    async def session_closed() -> bool:
        _, rows = await runtime.players_store.list_players()
        return rows[0]["time_on_server"] >= 0 and not _open_sessions(runtime)

    await until(session_closed)
    total, rows = await runtime.players_store.list_players(bots=True)
    assert total == 2  # the human and the bot


def _open_sessions(rt: Runtime) -> int:
    return len(rt.recorder._sessions)


async def test_a_store_that_fails_to_write_does_not_disturb_the_server_or_the_status(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def broken(*_a: Any, **_k: Any) -> Any:
        raise OSError("disk full")

    monkeypatch.setattr(runtime.players_store, "transact", broken)
    sup = runtime.supervisor
    await sup.send_command(f"fake_join 1 1 127.0.0.1 fp={FP} ^1Tester")
    await sup.send_command("fake_kill frag 1 1")
    await until(lambda: any(p.name == "^1Tester" for p in runtime.status.snapshot().players))

    async def logged() -> bool:
        await runtime.recorder.flush()  # does not raise
        return "could not be written" in caplog.text

    await until(logged)  # once the lookup has resolved there is something to write
    assert sup.state is RunState.RUNNING
    snap = runtime.status.snapshot()
    assert snap.state == "running" and snap.human_count == 1
    # and the server still answers
    reply = await runtime.console.query_line("sv_eventlog", lambda p: p.startswith('"sv_eventlog"'))
    assert '"sv_eventlog" is "1"' in reply


# --- when a match counts as played (player-stats: matches played) ------------------------------


async def _players(rt: Runtime, *, has: str) -> dict[str, list[dict[str, Any]]]:
    """The totals grouped by name, once the report that names ``has`` has been written."""
    grouped: dict[str, list[dict[str, Any]]] = {}

    async def written() -> bool:
        await rt.recorder.flush()
        _, rows = await rt.players_store.list_players(bots=True, limit=200)
        grouped.clear()
        for row in rows:
            grouped.setdefault(row["name"], []).append(row)
        # a reported player has time playing; the figures arrive in the same transaction
        return any(r["time_playing"] > 0 for r in grouped.get(has, []))

    await until(written)
    return grouped


async def _replay(rt: Runtime, fixture: str) -> None:
    await rt.supervisor.send_command(f"fake_report {fixture}")
    await rt.recorder.flush()


async def test_matches_played_counts_only_players_on_the_final_board_of_a_finished_match(
    runtime: Runtime,
) -> None:
    # a human leaves before the end, another joins late into the freed slot, one stays
    await _replay(runtime, "report_leaver.txt")
    got = await _players(runtime, has="^1Leav^7er")
    (stayer,) = got["^2Stay^7er"]
    (late,) = got["^4Late^7Joiner"]
    (leaver,) = got["^1Leav^7er"]
    (winner,) = got["[BOT]Sensible"]
    assert stayer["matches"] == 1
    assert late["matches"] == 1  # joining late does not matter
    assert leaver["matches"] == 0 and leaver["wins"] == 0
    assert leaver["time_playing"] > 0  # what they did is still counted
    assert winner["matches"] == 1 and winner["wins"] == 1

    # a human who is spectating when the match reaches its limit
    await _replay(runtime, "report_spectator_at_end.txt")
    got = await _players(runtime, has="^5Watch^7er")
    (watcher,) = got["^5Watch^7er"]
    assert watcher["matches"] == 0 and watcher["time_playing"] > 0
    assert sorted(p["matches"] for p in got["^2Stay^7er"]) == [1, 1]  # two captures, two keys

    # a match against bots counts, a team game's losing side included
    await _replay(runtime, "report_tdm_finished.txt")
    got = await _players(runtime, has="^3Team^7Tester")
    (tester,) = got["^3Team^7Tester"]
    assert tester["matches"] == 1 and tester["wins"] == 0
    assert got["[BOT]Scorcher"][0]["wins"] == 1

    # a match cut short counts for nobody
    await _replay(runtime, "report_unfinished.txt")
    got = await _players(runtime, has="^2Map^7Changer")
    (changer,) = got["^2Map^7Changer"]
    assert changer["matches"] == 0 and changer["time_playing"] > 0
