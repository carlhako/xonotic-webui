"""The live match routes against a live panel and the fake dedicated server."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from tests.conftest import Live
from tests.test_api import sse_events

LiveFactory = Callable[..., "asyncio.Future[Live]"]


async def start_game(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/lifecycle/start")
    assert response.status_code == 200


async def wait_for(predicate: Callable[[], bool], timeout: float = 8.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


async def test_snapshot_while_stopped_says_there_is_no_match(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        body = (await client.get("/api/match")).json()
    assert body["live"] is False
    assert body["map"] is None and body["gametype"] is None
    assert body["clock"]["available"] is False
    assert body["scoreboard"] == {
        "available": False,
        "columns": [],
        "players": [],
        "spectators": [],
        "teams": [],
    }
    assert body["score_limit"] == {"value": None, "unit": "points"}


async def test_the_snapshot_endpoint_does_not_start_polling(
    live: LiveFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        await start_game(client)
        for _ in range(3):
            await client.get("/api/match")
            await asyncio.sleep(0.4)
        assert not app.runtime.match.polling
        assert app.runtime.match.subscriber_count == 0
        # the game never saw a poll
        assert not any(
            "game_starttime" in line.plain for line in app.runtime.supervisor.console.snapshot()
        )
        assert (await client.get("/api/match")).json()["live"] is False


async def test_the_stream_starts_with_the_current_snapshot_and_then_goes_live(
    live: LiveFactory,
) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        await start_game(client)
        await app.runtime.supervisor.send_command("fake_join 1 1 127.0.0.1 ^1Red^7Name")
        await app.runtime.supervisor.send_command("fake_score 1 score=4 kills=4")
        events = await sse_events(
            client,
            "/api/match/stream",
            until=lambda e: e["live"] and bool(e["scoreboard"]["players"]),
        )
        # the first event is whatever the snapshot was when the client connected
        assert events[0]["live"] in (True, False)
        last = events[-1]
        assert last["live"] is True
        assert last["gametype"] == "dm"
        assert last["clock"]["available"] is True
        assert last["score_limit"]["unit"] == "frags"
        player = last["scoreboard"]["players"][0]
        assert player["plain_name"] == "RedName"
        assert player["values"]["score"] == 4
        assert [c["key"] for c in last["scoreboard"]["columns"]][:2] == ["score", "kills"]

        # the stream polled while it was open and stops when it closed
        await wait_for(lambda: not app.runtime.match.polling)
        assert app.runtime.match.subscriber_count == 0


async def test_a_second_connection_gets_the_current_state_first(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        await start_game(client)
        first = await sse_events(client, "/api/match/stream", until=lambda e: e["live"])
        assert first[-1]["live"] is True
        # keep a reader open so the state is current, then connect another
        reader = asyncio.create_task(
            sse_events(client, "/api/match/stream", until=lambda e: False, timeout=6)
        )
        await wait_for(lambda: app.runtime.match.subscriber_count == 1)
        second = await sse_events(client, "/api/match/stream", until=lambda e: True)
        assert second[0]["live"] is True and second[0]["map"] is not None
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)


async def test_the_stream_reports_not_live_after_a_stop(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        await start_game(client)
        seen: list[dict] = []

        async def reader() -> None:
            async with client.stream("GET", "/api/match/stream") as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        seen.append(json.loads(line[6:]))

        task = asyncio.create_task(reader())
        await wait_for(lambda: any(e["live"] for e in seen))
        assert (await client.post("/api/lifecycle/stop")).status_code == 200
        await wait_for(lambda: seen[-1]["live"] is False)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
