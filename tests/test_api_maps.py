"""Map, gametype, rotation and match-action routes against a live panel and the fake."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from tests.conftest import Live
from tests.helpers import PREVIEW_BYTES, fake_maps, write_pk3
from tests.test_player_recorder_e2e import FP, current_match_id, until, write_report
from xonotic_webui.players.store import Ops, PlayerStoreError

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
        assert by_name["stormkeep"]["package"] == "xonotic-data-maps.pk3"
        assert (
            by_name["stormkeep"]["package_size"]
            == (app.settings.game_root / "data" / "xonotic-data-maps.pk3").stat().st_size
        )
        assert by_name["stormkeep"]["pending_restart"] is False


async def test_a_package_added_while_running_is_pending_until_a_restart(
    live: LiveFactory,
) -> None:
    app = await live()
    pk3 = app.settings.userdir / "data" / "late.pk3"
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        await client.post("/api/lifecycle/start")
        await wait_status(client, "state", "running")
        write_pk3(pk3, {"latemap": {"gametypes": ["dm"]}})
        by_name = {m["name"]: m for m in (await client.get("/api/maps")).json()["maps"]}
        late = by_name["latemap"]
        assert (late["source"], late["package"], late["package_size"]) == (
            "user",
            "late.pk3",
            pk3.stat().st_size,
        )
        assert late["pending_restart"] is True
        assert by_name["stormkeep"]["pending_restart"] is False

        r = await client.post("/api/match/goto", json={"map": "latemap"})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "map_needs_restart"

        await client.post("/api/lifecycle/restart")
        await wait_status(client, "state", "running")
        by_name = {m["name"]: m for m in (await client.get("/api/maps")).json()["maps"]}
        assert by_name["latemap"]["pending_restart"] is False
        await client.post("/api/lifecycle/stop")


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


# --- play totals and details (map-control, player-stats) -------------------------------------

NOW = 1_800_000_000


async def seed_history(app: Live) -> None:
    """Two finished matches and one cut-short one on stormkeep, nothing anywhere else."""

    def work(ops: Ops) -> None:
        ann = ops.get_or_create_player("fp:ann", "^1Ann", is_bot=False, now=NOW)
        rex = ops.get_or_create_player("bot:rex", "[BOT]Rex", is_bot=True, now=NOW)
        for match_id, started, finished, ann_frags, rex_frags in (
            ("m1", NOW, True, 10, 4),
            ("m2", NOW + 100, True, 5, 6),
            ("m3", NOW + 200, False, 3, 0),
        ):
            m = ops.upsert_match(match_id, "stormkeep", "dm", started)
            ops.add_counters(m, ann, frags=ann_frags)
            ops.add_counters(m, rex, frags=rex_frags)
            ops.apply_report(m, finished=finished, duration=60, players=[])

    await app.runtime.players_store.transact(work)


async def test_maps_carry_their_play_totals(live: LiveFactory) -> None:
    app = await live()
    await seed_history(app)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        by_name = {m["name"]: m for m in (await client.get("/api/maps")).json()["maps"]}
    played = by_name["stormkeep"]
    assert (played["played"], played["frags"], played["last_played"]) == (2, 28, NOW + 200)
    others = [m for n, m in by_name.items() if n != "stormkeep"]
    assert others and all(
        (m["played"], m["frags"], m["last_played"]) == (0, 0, None) for m in others
    )


async def test_history_off_still_lists_every_map_with_null_totals(live: LiveFactory) -> None:
    app = await live()
    await seed_history(app)
    app.runtime.recorder.enabled = False
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.get("/api/maps")
    assert r.status_code == 200
    maps = r.json()["maps"]
    assert {m["name"] for m in maps} == set(fake_maps())
    assert all(
        m["played"] is None and m["frags"] is None and m["last_played"] is None for m in maps
    )


async def test_a_store_error_still_lists_every_map_with_null_totals(
    live: LiveFactory, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    app = await live()

    async def broken() -> dict:
        raise PlayerStoreError("disk on fire")

    monkeypatch.setattr(app.runtime.players_store, "map_totals", broken)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        first = await client.get("/api/maps")
        second = await client.get("/api/maps")
    for r in (first, second):
        assert r.status_code == 200
        maps = r.json()["maps"]
        assert {m["name"] for m in maps} == set(fake_maps())
        assert all(m["played"] is None for m in maps)
    assert caplog.text.count("map play totals are not available") == 1  # once per outage


async def test_map_stats_of_a_played_map(live: LiveFactory) -> None:
    app = await live()
    await seed_history(app)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.get("/api/maps/stormkeep/stats")
    assert r.status_code == 200
    body = r.json()
    assert (body["name"], body["played"], body["cut_short"], body["frags"]) == (
        "stormkeep",
        2,
        1,
        28,
    )
    assert (body["first_played"], body["last_played"]) == (NOW, NOW + 200)
    assert body["gametypes"] == [{"gametype": "dm", "played": 2}]
    assert [(f["name"], f["frags"], f["is_bot"]) for f in body["top_fraggers"]] == [
        ("^1Ann", 18, False),
        ("[BOT]Rex", 10, True),
    ]


async def test_map_stats_of_a_never_played_map_are_zeros(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.get("/api/maps/stormkeep/stats")
    assert r.status_code == 200
    assert r.json() == {
        "name": "stormkeep",
        "played": 0,
        "cut_short": 0,
        "frags": 0,
        "first_played": None,
        "last_played": None,
        "gametypes": [],
        "top_fraggers": [],
    }


async def test_map_stats_of_an_unknown_map_is_not_found(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.get("/api/maps/nowhere/stats")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "map_not_found"


async def test_map_stats_with_history_off_is_unavailable(live: LiveFactory) -> None:
    app = await live()
    app.runtime.recorder.enabled = False
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.get("/api/maps/stormkeep/stats")
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "players_unavailable"


async def test_map_stats_for_a_name_that_needs_url_encoding(live: LiveFactory) -> None:
    app = await live()
    write_pk3(app.settings.userdir / "data" / "odd.pk3", {"my map": {"gametypes": ["dm"]}})
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        names = {m["name"] for m in (await client.get("/api/maps")).json()["maps"]}
        assert "my map" in names
        r = await client.get("/api/maps/my%20map/stats")
    assert r.status_code == 200 and r.json()["name"] == "my map"


async def test_a_match_played_through_the_recorder_shows_in_the_map_list(
    live: LiveFactory, tmp_path: Path
) -> None:
    """The recorder's map name is the catalogue's name (design risk: map name mismatch)."""
    app = await live()
    sup = app.runtime.supervisor
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        await client.post("/api/lifecycle/start")
        await wait_status(client, "state", "running")
        playing = (await client.get("/api/status")).json()["map"]
        assert playing in fake_maps()

        await sup.send_command(f"fake_join 1 1 127.0.0.1 fp={FP} ^1Tester")
        await sup.send_command("fake_join 2 2 bot [BOT]Eureka")
        await until(lambda: app.runtime.recorder.store.is_open)
        await sup.send_command("fake_kill frag 1 2")
        await sup.send_command("fake_kill frag 1 2")
        await sup.send_command("fake_kill frag 2 1")
        report = write_report(tmp_path, current_match_id(app.runtime), finished=True)
        await sup.send_command("fake_emit ^7:end")
        await sup.send_command(f"fake_report {report}")
        await sup.send_command("fake_emit ^7:gameover")

        async def totals() -> tuple | None:
            by_name = {m["name"]: m for m in (await client.get("/api/maps")).json()["maps"]}
            m = by_name[playing]
            return (m["played"], m["frags"]) if m["played"] else None

        await until(totals)
        assert await totals() == (1, 3)
        last = {m["name"]: m for m in (await client.get("/api/maps")).json()["maps"]}[playing]
        assert isinstance(last["last_played"], int)
        stats = (await client.get(f"/api/maps/{playing}/stats")).json()
        assert [(f["name"], f["frags"], f["is_bot"]) for f in stats["top_fraggers"]] == [
            ("^1Tester", 2, False),
            ("[BOT]Eureka", 1, True),
        ]
        await client.post("/api/lifecycle/stop")
