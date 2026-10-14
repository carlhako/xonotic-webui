"""The players routes against a live panel with a seeded history (player-stats spec)."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable

import httpx
import pytest

from tests.conftest import Live
from xonotic_webui.players.store import Ops, ReportedPlayer

LiveFactory = Callable[..., "asyncio.Future[Live]"]

NOW = 1_800_000_000
FP = "dRXbACYQr56HZ6KBw0zOIi7K1hQ3sUdDvO+DxBuUlSA="


@pytest.fixture(autouse=True)
def _quiet_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_XONOTIC", "autopause_delay=0.2")


async def seed(live: Live) -> dict[str, int]:
    ids: dict[str, int] = {}

    def work(ops: Ops) -> None:
        match = ops.upsert_match("m1", "atelier", "dm", NOW)
        specs = [
            ("ann", f"fp:{FP}", "^1Ann", False, 10, 5, 30.0, 900.0),
            ("bob", "fp:bob-key", "Bob", False, 20, 0, 10.0, 100.0),
            ("rex", "bot:[bot]rex", "[BOT]Rex", True, 7, 7, 7.0, 50.0),
        ]
        for label, key, name, bot, frags, deaths, score, alive in specs:
            pid = ops.get_or_create_player(key, name, is_bot=bot, now=NOW)
            ids[label] = pid
            ops.add_counters(match, pid, frags=frags, deaths=deaths)
            ops.apply_report(
                match,
                finished=True,
                duration=600,
                players=[
                    (
                        pid,
                        ReportedPlayer(
                            score=score,
                            alivetime=alive,
                            wins=1 if label == "ann" else 0,
                            scoreboard_valid=True,
                            avglatency=30.0,
                            weapons={"vortex": {"hit": 50, "fired": 100, "frags": 3}},
                            achievements={"firstblood": 1},
                        ),
                    )
                ],
            )
            ops.open_session(pid, NOW - 600)
        ops.upsert_alias(ids["ann"], "Old Ann", NOW - 1000)

    await live.runtime.players_store.transact(work)
    return ids


async def test_the_default_list_is_sorted_by_frags_descending_without_bots(
    live: LiveFactory,
) -> None:
    app = await live()
    await seed(app)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        response = await client.get("/api/players")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [p["plain_name"] for p in body["players"]] == ["Bob", "Ann"]
    bob = body["players"][0]
    assert bob["kd"] == 20.0 and bob["is_bot"] is False and bob["matches"] == 1
    assert bob["accuracy"] == pytest.approx(0.5)
    assert bob["time_playing"] == 100.0
    assert "ip" not in str(body).lower().replace("zip", "")


async def test_sort_order_and_paging(live: LiveFactory) -> None:
    app = await live()
    await seed(app)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        asc = (await client.get("/api/players", params={"sort": "frags", "order": "asc"})).json()
        page = (await client.get("/api/players", params={"limit": 1, "offset": 1})).json()
    assert [p["plain_name"] for p in asc["players"]] == ["Ann", "Bob"]
    assert page["total"] == 2 and [p["plain_name"] for p in page["players"]] == ["Ann"]


@pytest.mark.parametrize(
    "params",
    [
        {"sort": "password"},
        {"sort": "frags; DROP TABLE players"},
        {"order": "sideways"},
        {"limit": 0},
        {"offset": -1},
        {"limit": "many"},
    ],
)
async def test_invalid_query_parameters_are_rejected(
    live: LiveFactory, params: dict[str, object]
) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        response = await client.get("/api/players", params=params)
    assert response.status_code == 422


async def test_limit_is_capped(live: LiveFactory) -> None:
    app = await live()

    def fill(ops: Ops) -> None:
        for i in range(250):
            ops.get_or_create_player(f"fp:{i}", f"P{i}", is_bot=False, now=NOW)

    await app.runtime.players_store.transact(fill)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        body = (await client.get("/api/players", params={"limit": 1000})).json()
    assert body["total"] == 250 and len(body["players"]) == 200


async def test_search_matches_an_old_name_and_bots_can_be_shown(live: LiveFactory) -> None:
    app = await live()
    ids = await seed(app)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        found = (await client.get("/api/players", params={"q": "old ann"})).json()
        none = (await client.get("/api/players", params={"q": "rex"})).json()
        with_bots = (await client.get("/api/players", params={"q": "rex", "bots": "true"})).json()
        all_bots = (await client.get("/api/players", params={"bots": "true"})).json()
    assert [p["id"] for p in found["players"]] == [ids["ann"]]
    assert none["total"] == 0
    assert [p["is_bot"] for p in with_bots["players"]] == [True]
    assert all_bots["total"] == 3


async def test_the_etag_round_trip(live: LiveFactory) -> None:
    app = await live()
    await seed(app)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        first = await client.get("/api/players")
        etag = first.headers["etag"]
        assert re.fullmatch(r'"\d+-[0-9a-f]+"', etag)
        again = await client.get("/api/players", headers={"If-None-Match": etag})
        assert again.status_code == 304 and again.content == b""
        # a different query is a different representation
        other = await client.get(
            "/api/players", params={"sort": "deaths"}, headers={"If-None-Match": etag}
        )
        assert other.status_code == 200 and other.headers["etag"] != etag
        # a write changes the revision, so the old tag no longer matches
        await app.runtime.players_store.transact(
            lambda ops: ops.get_or_create_player("fp:new", "New", is_bot=False, now=NOW)
        )
        changed = await client.get("/api/players", headers={"If-None-Match": etag})
        assert changed.status_code == 200 and changed.json()["total"] == 3


async def test_player_detail_has_no_full_fingerprint_and_no_address(live: LiveFactory) -> None:
    app = await live()
    ids = await seed(app)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        response = await client.get(f"/api/players/{ids['ann']}")
    assert response.status_code == 200
    body = response.json()
    assert body["key_prefix"] == FP[:8] and len(body["key_prefix"]) <= 8
    assert FP not in response.text
    assert "127.0.0.1" not in response.text
    assert body["plain_name"] == "Ann"
    assert [a["plain_name"] for a in body["aliases"]] == ["Ann", "Old Ann"]  # most recent first
    assert body["weapons"][0]["weapon"] == "vortex"
    assert body["weapons"][0]["accuracy"] == pytest.approx(0.5)
    assert body["achievements"] == [{"name": "firstblood", "count": 1}]
    assert body["damage_dealt"] == 0 and body["avg_latency"] == 30.0
    assert body["has_match_stats"] is True and body["sessions"] == 1


async def test_a_player_known_only_by_name_has_no_key_prefix(live: LiveFactory) -> None:
    app = await live()
    ids = await seed(app)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        body = (await client.get(f"/api/players/{ids['rex']}")).json()
    assert body["key_prefix"] is None and body["is_bot"] is True


async def test_an_unknown_player_is_a_structured_404(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        response = await client.get("/api/players/987654")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "player_not_found"


async def test_an_empty_history_is_an_empty_list(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        body = (await client.get("/api/players")).json()
    assert body["total"] == 0 and body["players"] == []


async def test_history_survives_a_panel_restart(live: LiveFactory) -> None:
    app = await live()
    await seed(app)
    path = app.settings.players_db
    assert path.is_file()
    again = await live()  # a second panel on the same state directory reads the same file
    async with httpx.AsyncClient(base_url=again.base_url) as client:
        body = (await client.get("/api/players")).json()
    assert body["total"] == 2
