"""The match history routes against a live panel with a seeded history (match-history spec)."""

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


@pytest.fixture(autouse=True)
def _quiet_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_XONOTIC", "autopause_delay=0.2")


def rep(**kw: object) -> ReportedPlayer:
    kw.setdefault("scoreboard_valid", True)
    return ReportedPlayer(**kw)  # type: ignore[arg-type]


async def seed(live: Live) -> dict[str, int]:
    """Five matches: a vs-bots dm, a team game, a ctf with extra columns, a cut-short one and
    a crashed one; plus a bots-only match that is never listed."""
    ids: dict[str, int] = {}

    def work(ops: Ops) -> None:
        def player(key: str, name: str, bot: bool = False) -> int:
            return ops.get_or_create_player(key, name, is_bot=bot, now=NOW)

        ace = ids["ace"] = player("fp:ace", "^1Ace")
        bee = ids["bee"] = player("fp:bee", "Bee")
        rex = ids["rex"] = player("bot:[bot]rex", "[BOT]Rex", True)
        tom = ids["tom"] = player("bot:[bot]tom", "[BOT]Tom", True)

        # 1. one human against two bots, deathmatch, won by Ace
        m = ids["dm"] = ops.upsert_match("m-dm", "boil", "dm", NOW)
        ops.add_counters(m, ace, frags=9, deaths=2, name="^1Ace")
        ops.add_counters(m, rex, frags=3, deaths=5)
        ops.add_counters(m, tom, frags=1, deaths=6)
        ops.apply_report(
            m,
            finished=True,
            duration=300,
            players=[
                (
                    ace,
                    rep(
                        wins=1,
                        board_pos=1,
                        name="^1Ace",
                        scores={"score": 9.0, "kills": 9.0},
                        alivetime=290,
                        avglatency=21,
                    ),
                ),
                (rex, rep(board_pos=2, name="[BOT]Rex", scores={"score": 3.0, "kills": 3.0})),
                (tom, rep(board_pos=3, name="[BOT]Tom", scores={"score": 1.0})),
            ],
        )

        # 2. a team game: two humans and a bot, blue wins
        m = ids["tdm"] = ops.upsert_match("m-tdm", "atelier", "tdm", NOW + 100)
        ops.add_counters(m, ace, frags=4, deaths=4)
        ops.add_counters(m, bee, frags=6, deaths=1)
        ops.add_counters(m, rex, frags=2, deaths=5)
        ops.apply_report(
            m,
            finished=True,
            duration=400,
            players=[
                (ace, rep(team=5, board_pos=3, name="^1Ace", scores={"score": 4.0})),
                (bee, rep(team=14, board_pos=1, wins=1, name="Bee", scores={"score": 6.0})),
                (rex, rep(team=14, board_pos=2, wins=1, name="[BOT]Rex", scores={"score": 2.0})),
            ],
            teams={14: {"score": 8.0}, 5: {"score": 4.0}},
        )

        # 3. ctf with a player who left: extra columns, a "not at end" player
        m = ids["ctf"] = ops.upsert_match("m-ctf", "boil", "ctf", NOW + 200)
        ops.add_counters(m, ace, frags=1)
        ops.add_counters(m, bee, frags=1)
        ops.apply_report(
            m,
            finished=True,
            duration=500,
            players=[
                (
                    ace,
                    rep(
                        team=5,
                        board_pos=1,
                        name="^1Ace",
                        scores={"score": 40.0, "caps": 2.0, "captime": 2500.0},
                    ),
                ),
                (
                    bee,
                    ReportedPlayer(
                        team=14, name="Bee", scores={"score": 3.0}, alivetime=60, avglatency=33
                    ),
                ),
            ],
            teams={5: {"score": 40.0, "caps": 2.0}, 14: {"score": 3.0}},
        )

        # 4. cut short, with Bee only
        m = ids["cut"] = ops.upsert_match("m-cut", "atelier", "dm", NOW + 300)
        ops.add_counters(m, bee, frags=2)
        ops.apply_report(
            m,
            finished=False,
            duration=30,
            players=[(bee, rep(board_pos=1, name="Bee", scores={"score": 2.0}))],
        )

        # 5. no report (a crash): live counters only
        m = ids["crash"] = ops.upsert_match("m-crash", "boil", "dm", NOW + 400)
        ops.add_counters(m, ace, frags=2, deaths=1)
        ops.add_counters(m, rex, frags=1, deaths=2)

        # bots only: never listed
        m = ids["bots"] = ops.upsert_match("m-bots", "boil", "dm", NOW + 500)
        ops.add_counters(m, rex, frags=5)
        ops.add_counters(m, tom, deaths=5)

    await live.runtime.players_store.transact(work)
    return ids


async def test_the_list_is_newest_first_and_leaves_out_bots_only_matches(
    live: LiveFactory,
) -> None:
    app = await live()
    await seed(app)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        response = await client.get("/api/matches")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert [m["map"] for m in body["matches"]] == ["boil", "atelier", "boil", "atelier", "boil"]
    assert [m["gametype"] for m in body["matches"]] == ["dm", "dm", "ctf", "tdm", "dm"]
    assert [m["outcome"] for m in body["matches"]] == [
        "no_report",
        "cut_short",
        "finished",
        "finished",
        "finished",
    ]


async def test_a_listed_match_has_its_summary(live: LiveFactory) -> None:
    app = await live()
    ids = await seed(app)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        body = (await client.get("/api/matches")).json()
    by_id = {m["id"]: m for m in body["matches"]}
    dm = by_id[ids["dm"]]
    assert dm["started_at"] == NOW and dm["duration"] == 300
    assert (dm["humans"], dm["bots"], dm["vs_bots"]) == (1, 2, True)
    assert dm["winner"] == {
        "kind": "player",
        "player_id": ids["ace"],
        "name": "^1Ace",
        "plain_name": "Ace",
        "is_bot": False,
        "others": 0,
    }
    tdm = by_id[ids["tdm"]]
    assert (tdm["humans"], tdm["bots"], tdm["vs_bots"]) == (2, 1, False)
    assert tdm["winner"] == {"kind": "team", "team": 14, "color": "blue"}
    assert by_id[ids["ctf"]]["winner"] is None  # nobody has a win
    assert by_id[ids["cut"]]["winner"] is None and by_id[ids["cut"]]["duration"] == 30
    crash = by_id[ids["crash"]]
    assert crash["winner"] is None and crash["duration"] is None
    assert "127.0.0.1" not in str(body)


async def test_filters_combine(live: LiveFactory) -> None:
    app = await live()
    ids = await seed(app)

    async def got(**params: object) -> list[int]:
        async with httpx.AsyncClient(base_url=app.base_url) as client:
            response = await client.get("/api/matches", params=params)
        assert response.status_code == 200
        return [m["id"] for m in response.json()["matches"]]

    assert await got(map="boil") == [ids["crash"], ids["ctf"], ids["dm"]]
    assert await got(gametype="ctf") == [ids["ctf"]]
    assert await got(map="boil", gametype="dm") == [ids["crash"], ids["dm"]]
    assert ids["dm"] not in await got(vs_bots="false")
    assert await got(player=ids["bee"]) == [
        ids["cut"],
        ids["ctf"],
        ids["tdm"],
    ]  # includes ctf, left
    assert await got(player=ids["bee"], map="atelier", vs_bots="false") == [ids["cut"], ids["tdm"]]
    assert await got(map="nowhere") == []


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"offset": -1}, {"player": "ace"}, {"player": 0}, {"vs_bots": "maybe"}],
)
async def test_invalid_query_parameters_are_rejected(
    live: LiveFactory, params: dict[str, object]
) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        response = await client.get("/api/matches", params=params)
    assert response.status_code == 422


async def test_paging_and_the_limit_cap(live: LiveFactory) -> None:
    app = await live()

    def fill(ops: Ops) -> None:
        pid = ops.get_or_create_player("fp:a", "A", is_bot=False, now=NOW)
        for i in range(230):
            ops.add_counters(ops.upsert_match(f"m{i}", "boil", "dm", NOW + i), pid, frags=1)

    await app.runtime.players_store.transact(fill)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        page = (await client.get("/api/matches", params={"limit": 2, "offset": 1})).json()
        big = (await client.get("/api/matches", params={"limit": 1000})).json()
    assert page["total"] == 230 and len(page["matches"]) == 2
    assert [m["started_at"] for m in page["matches"]] == [NOW + 228, NOW + 227]
    assert big["total"] == 230 and len(big["matches"]) == 200


async def test_the_etag_round_trip(live: LiveFactory) -> None:
    app = await live()
    await seed(app)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        first = await client.get("/api/matches")
        etag = first.headers["etag"]
        assert re.fullmatch(r'"\d+--[0-9a-f]+"', etag)  # no current match: empty middle
        again = await client.get("/api/matches", headers={"If-None-Match": etag})
        assert again.status_code == 304 and again.content == b""
        other = await client.get(
            "/api/matches", params={"map": "boil"}, headers={"If-None-Match": etag}
        )
        assert other.status_code == 200 and other.headers["etag"] != etag
        await app.runtime.players_store.transact(
            lambda ops: ops.upsert_match("m-new", "boil", "dm", NOW + 999)
        )
        changed = await client.get("/api/matches", headers={"If-None-Match": etag})
        assert changed.status_code == 200


async def test_the_etag_changes_when_the_current_match_changes(live: LiveFactory) -> None:
    app = await live()
    await seed(app)
    recorder = app.runtime.recorder
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        etag = (await client.get("/api/matches")).headers["etag"]
        recorder.on_line("^7:gamestart:dm_boil:0.77.1")
        assert recorder.current_match_id == "0.77.1"
        changed = await client.get("/api/matches", headers={"If-None-Match": etag})
        # no database write happened, and the list still differs
        assert changed.status_code == 200 and changed.headers["etag"] != etag
        etag2 = changed.headers["etag"]
        same = await client.get("/api/matches", headers={"If-None-Match": etag2})
        assert same.status_code == 304
        recorder.on_line("^7:gamestart:dm_boil:0.88.2")
        again = await client.get("/api/matches", headers={"If-None-Match": etag2})
        assert again.status_code == 200 and again.headers["etag"] != etag2


async def test_a_match_without_a_report_is_in_progress_while_it_is_the_current_one(
    live: LiveFactory,
) -> None:
    app = await live()
    recorder = app.runtime.recorder
    recorder.on_line("^7:gamestart:dm_boil:0.5.5")

    def work(ops: Ops) -> None:
        pid = ops.get_or_create_player("fp:a", "A", is_bot=False, now=NOW)
        ops.add_counters(ops.upsert_match("0.5.5", "boil", "dm", NOW), pid, frags=1)
        ops.add_counters(ops.upsert_match("0.4.4", "boil", "dm", NOW - 600), pid, frags=1)

    await app.runtime.players_store.transact(work)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        body = (await client.get("/api/matches")).json()
        assert [m["outcome"] for m in body["matches"]] == ["in_progress", "no_report"]
        detail = (await client.get(f"/api/matches/{body['matches'][0]['id']}")).json()
    assert detail["outcome"] == "in_progress"
    # the game's own id never reaches the interface
    assert "0.5.5" not in str(body) and "0.5.5" not in str(detail)


async def test_a_match_with_its_report_is_finished_even_while_current(
    live: LiveFactory,
) -> None:
    app = await live()
    app.runtime.recorder.on_line("^7:gamestart:dm_boil:0.5.5")

    def work(ops: Ops) -> None:
        pid = ops.get_or_create_player("fp:a", "A", is_bot=False, now=NOW)
        pk = ops.upsert_match("0.5.5", "boil", "dm", NOW)
        ops.apply_report(pk, finished=True, duration=60, players=[(pid, rep(wins=1))])

    await app.runtime.players_store.transact(work)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        body = (await client.get("/api/matches")).json()
    assert body["matches"][0]["outcome"] == "finished"


async def test_a_deathmatch_in_board_order_with_those_not_at_the_end_last(
    live: LiveFactory,
) -> None:
    app = await live()
    ids = await seed(app)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        body = (await client.get(f"/api/matches/{ids['dm']}")).json()
    assert body["id"] == ids["dm"] and body["board_kept"] is True and body["vs_bots"] is True
    board = body["scoreboard"]
    assert [c["key"] for c in board["columns"]] == ["score", "kills", "deaths", "suicides"]
    assert [c["label"] for c in board["columns"]] == ["Score", "Kills", "Deaths", "Suicides"]
    assert (board["columns"][0]["primary"], board["columns"][0]["lower_is_better"]) == (True, False)
    assert [p["plain_name"] for p in board["players"]] == ["Ace", "[BOT]Rex", "[BOT]Tom"]
    ace = board["players"][0]
    assert ace["name"] == "^1Ace" and ace["bot"] is False and ace["player_id"] == ids["ace"]
    assert ace["values"] == {"score": 9, "kills": 9, "deaths": 0, "suicides": 0}
    assert ace["ping"] == 21 and ace["time_s"] == 290 and ace["at_end"] is True
    assert board["teams"] == []


async def test_a_team_game_has_teams_with_colours_and_players_with_their_team(
    live: LiveFactory,
) -> None:
    app = await live()
    ids = await seed(app)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        body = (await client.get(f"/api/matches/{ids['tdm']}")).json()
    board = body["scoreboard"]
    assert board["teams"] == [
        {"team": 14, "color": "blue", "values": {"score": 8}},
        {"team": 5, "color": "red", "values": {"score": 4}},
    ]
    assert [(p["plain_name"], p["team"]) for p in board["players"]] == [
        ("Bee", 14),
        ("[BOT]Rex", 14),
        ("Ace", 5),
    ]
    assert body["winner"] == {"kind": "team", "team": 14, "color": "blue"}


async def test_a_team_that_scored_nothing_shows_zero_not_missing(live: LiveFactory) -> None:
    app = await live()

    def work(ops: Ops) -> None:
        a = ops.get_or_create_player("fp:a", "A", is_bot=False, now=NOW)
        b = ops.get_or_create_player("fp:b", "B", is_bot=False, now=NOW)
        m = ops.upsert_match("m", "boil", "ctf", NOW)
        ops.apply_report(
            m,
            finished=True,
            duration=60,
            players=[
                (a, rep(team=14, board_pos=1, wins=1, scores={"score": 5.0, "caps": 1.0})),
                (b, rep(team=5, board_pos=2, scores={})),
            ],
            teams={14: {"score": 5.0, "caps": 1.0}, 5: {}},  # red wrote no lines at all
        )

    await app.runtime.players_store.transact(work)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        listing = (await client.get("/api/matches")).json()
        body = (await client.get(f"/api/matches/{listing['matches'][0]['id']}")).json()
    assert body["scoreboard"]["teams"] == [
        {"team": 14, "color": "blue", "values": {"score": 5, "caps": 1}},
        {"team": 5, "color": "red", "values": {"score": 0, "caps": 0}},
    ]


async def test_a_ctf_match_has_extra_columns_and_a_player_who_was_not_there_at_the_end(
    live: LiveFactory,
) -> None:
    app = await live()
    ids = await seed(app)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        body = (await client.get(f"/api/matches/{ids['ctf']}")).json()
    board = body["scoreboard"]
    assert [c["key"] for c in board["columns"]] == [
        "score",
        "kills",
        "deaths",
        "suicides",
        "caps",
        "captime",
    ]
    assert [c["label"] for c in board["columns"]][-2:] == ["Captures", "Capture time"]
    assert [(p["plain_name"], p["at_end"]) for p in board["players"]] == [
        ("Ace", True),
        ("Bee", False),
    ]
    assert board["players"][0]["values"]["caps"] == 2
    assert board["players"][1]["ping"] == 33 and board["players"][1]["time_s"] == 60


async def test_a_match_without_a_report_shows_its_live_counters(live: LiveFactory) -> None:
    app = await live()
    ids = await seed(app)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        body = (await client.get(f"/api/matches/{ids['crash']}")).json()
    assert body["outcome"] == "no_report"
    board = body["scoreboard"]
    assert [p["plain_name"] for p in board["players"]] == ["Ace", "[BOT]Rex"]
    assert board["players"][0]["values"] == {"score": 0, "kills": 2, "deaths": 1, "suicides": 0}
    assert [p["at_end"] for p in board["players"]] == [None, None]
    assert [p["ping"] for p in board["players"]] == [None, None]


async def test_an_unknown_match_is_a_structured_404(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        response = await client.get("/api/matches/987654")
        bad = await client.get("/api/matches/not-a-number")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "match_not_found"
    assert bad.status_code == 422


async def test_both_routes_answer_503_when_history_is_not_recorded(live: LiveFactory) -> None:
    app = await live()
    app.runtime.recorder.enabled = False
    try:
        async with httpx.AsyncClient(base_url=app.base_url) as client:
            listing = await client.get("/api/matches")
            detail = await client.get("/api/matches/1")
    finally:
        app.runtime.recorder.enabled = True  # so shutdown closes the store
    for response in (listing, detail):
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "players_unavailable"


async def test_an_empty_history_is_an_empty_list(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        body = (await client.get("/api/matches")).json()
    assert body["total"] == 0 and body["matches"] == []
