"""Map, gametype, rotation and match-action routes against a live panel and the fake."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from tests.conftest import Live
from tests.helpers import PREVIEW_BYTES, fake_maps

LiveFactory = Callable[..., "asyncio.Future[Live]"]

FAST = "autopause_delay=0.2,endmatch_delay=0.05,scoreboard_delay=0.3"


@pytest.fixture(autouse=True)
def _fast_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_XONOTIC", FAST)


async def action_state(client: httpx.AsyncClient, want: str, timeout: float = 8.0) -> dict:
    async with asyncio.timeout(timeout):
        while True:
            action = (await client.get("/api/status")).json()["action"]
            if action is not None and action["state"] == want:
                return action
            await asyncio.sleep(0.05)


async def wait_status(
    client: httpx.AsyncClient, key: str, value: object, timeout: float = 8.0
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while (await client.get("/api/status")).json()[key] != value:
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"status {key} never became {value!r}")
        await asyncio.sleep(0.05)


# --- catalogue ------------------------------------------------------------------------


async def test_maps_are_listed_in_full_while_the_server_is_stopped(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        assert (await client.get("/api/status")).json()["state"] == "stopped"
        body = (await client.get("/api/maps")).json()
        by_name = {m["name"]: m for m in body["maps"]}
        assert set(by_name) == set(fake_maps())
        assert "_hudsetup" not in by_name
        assert by_name["stormkeep"]["gametypes"] == ["dm", "tdm"]
        assert by_name["stormkeep"]["title"] == "Stormkeep"
        assert by_name["stormkeep"]["preview"] is True
        assert by_name["stormkeep"]["source"] == "game"


async def test_a_preview_image_is_streamed_and_a_missing_one_is_a_404(
    live: LiveFactory,
) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.get("/api/maps/stormkeep/preview")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/jpeg"
        assert r.content == PREVIEW_BYTES
        missing = await client.get("/api/maps/nosuchmap/preview")
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "no_preview"


async def test_gametypes_offered_and_selection(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        body = (await client.get("/api/gametypes")).json()
        assert len(body["gametypes"]) == 20
        offered = {g["id"] for g in body["gametypes"] if g["offered"]}
        assert offered == {g for gametypes in fake_maps().values() for g in gametypes}
        assert body["selected"] is None and body["effective"] is None

        r = await client.put("/api/gametype", json={"gametype": "tdm"})
        assert r.status_code == 200
        assert r.json() == {"gametype": "tdm", "apply": "next_start"}
        assert (await client.get("/api/gametypes")).json()["effective"] == "tdm"

        r = await client.put("/api/gametype", json={"gametype": "ca"})  # no map plays it
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "gametype_unavailable"
        r = await client.put("/api/gametype", json={"gametype": "nosuch"})
        assert r.json()["detail"]["code"] == "unknown_gametype"


async def test_the_gametype_applies_at_the_next_map_and_survives_a_restart(
    live: LiveFactory,
) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        await client.post("/api/lifecycle/start")
        assert (await client.get("/api/status")).json()["gametype"] == "dm"
        r = await client.put("/api/gametype", json={"gametype": "tdm"})
        assert r.json()["apply"] == "next_map"
        status = (await client.get("/api/status")).json()
        assert status["gametype"] == "dm"  # the current match continues
        await client.post("/api/console/command", json={"command": "changelevel boil"})
        await wait_status(client, "gametype", "tdm")
        await client.post("/api/lifecycle/restart")
        assert (await client.get("/api/status")).json()["gametype"] == "tdm"
        await client.post("/api/lifecycle/stop")


async def test_rotation_round_trip_and_validation(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.put("/api/rotation", json={"maps": ["stormkeep", "nosuch"]})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "map_not_installed"

        await client.put("/api/gametype", json={"gametype": "tdm"})
        r = await client.put(
            "/api/rotation", json={"maps": ["stormkeep", "catharsis", "boil"], "shuffle": False}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["apply"] == "next_start"
        assert body["rotation"]["shuffle"] is False
        assert body["rotation"]["gametype"] == "tdm"
        assert [(m["name"], m["supported"]) for m in body["rotation"]["maps"]] == [
            ("stormkeep", True),
            ("catharsis", False),
            ("boil", True),
        ]
        assert (await client.get("/api/rotation")).json() == body["rotation"]


# --- actions -----------------------------------------------------------------------------


async def test_actions_report_not_running_when_stopped(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        for path, body in (
            ("/api/match/skip", None),
            ("/api/match/restart", None),
            ("/api/match/goto", {"map": "boil"}),
        ):
            r = await client.post(path, json=body)
            assert r.status_code == 409, path
            assert r.json()["detail"]["code"] == "not_running"


async def test_goto_validation_codes(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        await client.post("/api/lifecycle/start")
        r = await client.post("/api/match/goto", json={"map": "nosuchmap"})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "map_not_installed"
        await client.put("/api/gametype", json={"gametype": "tdm"})
        r = await client.post("/api/match/goto", json={"map": "catharsis"})
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["code"] == "map_unsupported_gametype"
        assert detail["message"] == "catharsis does not support Team Deathmatch"
        assert (await client.get("/api/status")).json()["action"] is None
        await client.post("/api/lifecycle/stop")


async def test_goto_skip_and_restart_end_to_end_on_an_idle_paused_server(
    live: LiveFactory,
) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        await client.post("/api/lifecycle/start")
        await asyncio.sleep(0.5)  # the empty fake server has paused itself

        r = await client.post("/api/match/goto", json={"map": "warfare"})
        assert r.status_code == 202
        assert r.json()["kind"] == "goto" and r.json()["map"] == "warfare"
        await action_state(client, "done")
        assert (await client.get("/api/status")).json()["map"] == "warfare"

        await asyncio.sleep(0.5)  # idle again
        r = await client.post("/api/match/skip")
        assert r.status_code == 202
        done = await action_state(client, "done")
        assert done["kind"] == "skip"
        assert (await client.get("/api/status")).json()["map"] != "warfare"

        before = (await client.get("/api/status")).json()["map"]
        r = await client.post("/api/match/restart")
        assert r.status_code == 202
        await action_state(client, "done")
        assert (await client.get("/api/status")).json()["map"] == before
        await client.post("/api/lifecycle/stop")


async def test_a_second_action_is_a_409_and_others_see_it_pending(
    live: LiveFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a long scoreboard keeps the skip pending while the second request and the other
    # browser look at it
    monkeypatch.setenv("FAKE_XONOTIC", "endmatch_delay=0.05,scoreboard_delay=3,autopause_delay=30")
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        await client.post("/api/lifecycle/start")
        await client.post("/api/console/command", json={"command": "fake_join 1 1 127.0.0.1 Human"})
        await wait_status(client, "human_count", 1)
        r = await client.post("/api/match/skip")
        assert r.status_code == 202
        # another browser, a moment later, sees the skip pending in the snapshot
        async with httpx.AsyncClient(base_url=app.base_url) as other:
            first = None
            async with other.stream("GET", "/api/status/stream") as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        first = json.loads(line[6:])
                        break
            assert first is not None and first["action"]["kind"] == "skip"
            assert first["action"]["state"] == "pending"
        r = await client.post("/api/match/goto", json={"map": "warfare"})
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "action_in_progress"
        await action_state(client, "done")
        await client.post("/api/lifecycle/stop")


async def test_change_now_goes_to_a_map_that_supports_the_new_gametype(
    live: LiveFactory,
) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        await client.post("/api/lifecycle/start")
        assert (await client.get("/api/status")).json()["gametype"] == "dm"
        # the score limit is described in captures once capture the flag is selected
        await client.put("/api/gametype", json={"gametype": "ctf"})
        settings = (await client.get("/api/settings")).json()
        assert settings["score_unit"] == "captures"

        r = await client.post("/api/match/goto", json={"map": "catharsis"})
        assert r.status_code == 202
        await action_state(client, "done")
        status = (await client.get("/api/status")).json()
        assert (status["map"], status["gametype"]) == ("catharsis", "ctf")
        await client.post("/api/lifecycle/stop")
