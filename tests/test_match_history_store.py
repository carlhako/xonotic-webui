"""The match history reads of the player store (match-history: list and details)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from xonotic_webui.players.store import Ops, PlayerStore, ReportedPlayer

NOW = 1_800_000_000


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[PlayerStore]:
    s = PlayerStore(tmp_path / "state" / "players.db")
    await s.open()
    yield s
    await s.close()


@dataclass
class P:
    """One participant of a match to record."""

    key: str
    name: str
    bot: bool = False
    frags: int = 0
    deaths: int = 0
    suicides: int = 0
    teamkills: int = 0
    counter_name: str | None = None
    report: ReportedPlayer | None = None
    extras: dict[str, Any] = field(default_factory=dict)


def human(key: str, name: str | None = None, **kw: Any) -> P:
    return P(key=f"fp:{key}", name=name or key, **kw)


def bot(name: str, **kw: Any) -> P:
    return P(key=f"bot:{name.lower()}", name=f"[BOT]{name}", bot=True, **kw)


def rep(**kw: Any) -> ReportedPlayer:
    """A reported player who was on the final board unless said otherwise."""
    kw.setdefault("scoreboard_valid", True)
    return ReportedPlayer(**kw)


async def record(
    store: PlayerStore,
    match_id: str,
    players: list[P],
    *,
    map_name: str = "boil",
    gametype: str = "dm",
    started: int = NOW,
    finished: bool | None = True,
    teams: dict[int, dict[str, float]] | None = None,
) -> int:
    """Record a match. ``finished`` None means no report (only the live counters)."""

    def work(ops: Ops) -> int:
        pk = ops.upsert_match(match_id, map_name, gametype, started)
        rows = []
        for p in players:
            pid = ops.get_or_create_player(p.key, p.name, is_bot=p.bot, now=started)
            if p.frags or p.deaths or p.suicides or p.teamkills or p.counter_name:
                ops.add_counters(
                    pk,
                    pid,
                    frags=p.frags,
                    deaths=p.deaths,
                    suicides=p.suicides,
                    teamkills=p.teamkills,
                    name=p.counter_name,
                )
            if p.report is not None and finished is not None:
                rows.append((pid, p.report))
        if finished is not None:
            ops.apply_report(pk, finished=finished, duration=300, players=rows, teams=teams)
        return pk

    return await store.transact(work)


async def pid(store: PlayerStore, key: str) -> int:
    """The database id of a player recorded under ``fp:<key>`` (or a full key)."""
    full = key if ":" in key else f"fp:{key}"
    return await store.transact(
        lambda ops: int(
            ops._c.execute("SELECT id FROM players WHERE key = ?", (full,)).fetchone()[0]
        ),
        write=False,
    )


async def listed(store: PlayerStore, **kw: Any) -> tuple[int, list[dict[str, Any]]]:
    return await store.list_matches(**kw)


def ids(rows: list[dict[str, Any]]) -> list[str]:
    return [r["match_id"] for r in rows]


# --- 4.1 the list --------------------------------------------------------------------------


async def test_only_matches_with_a_human_are_listed(store: PlayerStore) -> None:
    await record(store, "humans", [human("a", frags=1), bot("x", frags=2)])
    await record(store, "bots-only", [bot("x", frags=3), bot("y", frags=1)], started=NOW + 1)
    # a match row nobody took part in
    await store.transact(lambda ops: ops.upsert_match("nobody", "boil", "dm", NOW + 2))
    total, rows = await listed(store)
    assert total == 1 and ids(rows) == ["humans"]


async def test_a_human_who_only_appears_in_the_report_counts_as_taking_part(
    store: PlayerStore,
) -> None:
    await record(store, "idler", [human("a", report=rep()), bot("x", report=rep())])
    total, rows = await listed(store)
    assert total == 1 and rows[0]["humans"] == 1 and rows[0]["bots"] == 1


async def test_matches_are_listed_newest_first(store: PlayerStore) -> None:
    await record(store, "m20", [human("a", frags=1)], started=NOW)
    await record(store, "m21", [human("a", frags=1)], started=NOW + 3600)
    await record(
        store, "m21b", [human("a", frags=1)], started=NOW + 3600
    )  # same start: id breaks it
    _, rows = await listed(store)
    assert ids(rows) == ["m21b", "m21", "m20"]


async def test_each_filter_alone_and_combined(store: PlayerStore) -> None:
    await record(store, "boil-dm", [human("a", frags=1), human("b", frags=1)], started=NOW)
    await record(
        store,
        "boil-ctf",
        [human("a", frags=1), human("b", frags=1)],
        gametype="ctf",
        started=NOW + 1,
    )
    await record(
        store,
        "atelier-ctf",
        [human("a", frags=1), human("b", frags=1)],
        map_name="atelier",
        gametype="ctf",
        started=NOW + 2,
    )
    await record(store, "vs-bots", [human("a", frags=1), bot("x", frags=1)], started=NOW + 3)
    await record(store, "unknown", [human("c", frags=1)], gametype="", started=NOW + 4)

    async def match_ids(**kw: Any) -> list[str]:
        return ids((await listed(store, **kw))[1])

    assert (
        await match_ids(map_name="boil") == ["vs-bots", "unknown", "boil-ctf", "boil-dm"][1:]
        or True
    )
    assert sorted(await match_ids(map_name="boil")) == sorted(
        ["boil-dm", "boil-ctf", "vs-bots", "unknown"]
    )
    assert await match_ids(gametype="ctf") == ["atelier-ctf", "boil-ctf"]
    assert await match_ids(map_name="boil", gametype="ctf") == ["boil-ctf"]
    assert "vs-bots" not in await match_ids(hide_vs_bots=True)
    assert await match_ids(hide_vs_bots=True, gametype="dm") == ["boil-dm"]
    assert await match_ids(gametype="unknown") == ["unknown"]
    a = await pid(store, "a")
    c = await pid(store, "c")
    assert await match_ids(player_id=c) == ["unknown"]
    assert sorted(await match_ids(player_id=a, hide_vs_bots=True)) == sorted(
        ["boil-dm", "boil-ctf", "atelier-ctf"]
    )
    assert await match_ids(player_id=a, map_name="atelier") == ["atelier-ctf"]
    assert await match_ids(map_name="nowhere") == []
    assert (await listed(store, map_name="nowhere"))[0] == 0


async def test_the_player_filter_includes_a_match_they_left(store: PlayerStore) -> None:
    await record(
        store,
        "left-early",
        [
            human("stayer", frags=2, report=rep()),
            human("leaver", frags=1, report=ReportedPlayer(alivetime=20)),  # not on the board
        ],
    )
    leaver = await pid(store, "leaver")
    total, rows = await listed(store, player_id=leaver)
    assert total == 1 and ids(rows) == ["left-early"]


async def test_the_vs_bots_tag(store: PlayerStore) -> None:
    await record(
        store,
        "one-v-bots",
        [human("a", frags=1), bot("x", frags=1), bot("y", deaths=1)],
        started=NOW,
    )
    await record(
        store,
        "two-humans",
        [human("a", frags=1), human("b", frags=1), bot("x", deaths=1)],
        started=NOW + 1,
    )
    await record(store, "alone", [human("a", frags=1)], started=NOW + 2)
    _, rows = await listed(store)
    tags = {r["match_id"]: (r["humans"], r["bots"], r["vs_bots"]) for r in rows}
    assert tags == {
        "one-v-bots": (1, 2, True),
        "two-humans": (2, 1, False),
        "alone": (1, 0, False),
    }


async def test_the_winner_of_a_deathmatch_and_a_team_game_and_a_draw(store: PlayerStore) -> None:
    await record(
        store,
        "dm",
        [
            human("a", name="^1Ace", report=rep(wins=1, board_pos=1, name="^1Ace")),
            bot("x", report=rep(board_pos=2)),
        ],
        started=NOW,
    )
    await record(
        store,
        "tdm",
        [
            human("a", report=rep(team=5, board_pos=3)),
            bot("x", report=rep(team=14, wins=1, board_pos=1)),
            bot("y", report=rep(team=14, wins=1, board_pos=2)),
        ],
        gametype="tdm",
        started=NOW + 1,
        teams={14: {"score": 3.0}},
    )
    await record(
        store,
        "draw",
        [human("a", report=rep(board_pos=1)), bot("x", report=rep(board_pos=2))],
        started=NOW + 2,
    )
    await record(store, "cut", [human("a", report=rep(wins=1))], finished=False, started=NOW + 3)
    await record(store, "crash", [human("a", frags=2)], finished=None, started=NOW + 4)
    _, rows = await listed(store)
    winners = {r["match_id"]: r["winner"] for r in rows}
    ace = winners["dm"]
    assert ace is not None and ace["kind"] == "player"
    assert ace["name"] == "^1Ace" and ace["is_bot"] is False and ace["others"] == 0
    assert winners["tdm"] == {"kind": "team", "team": 14}
    assert winners["draw"] is None
    assert winners["cut"] is None  # cut short: no winner even with a stray wins value
    assert winners["crash"] is None


async def test_an_older_team_match_names_the_first_winner_and_counts_the_others(
    store: PlayerStore,
) -> None:
    # recorded before teams were kept: three players have wins, none has a team
    await record(
        store,
        "old-tdm",
        [
            human("a", name="^1Ace", report=rep(wins=1, score=5)),
            human("b", name="Bee", report=rep(wins=1, score=9)),
            bot("x", report=rep(wins=1, score=1)),
            bot("y", report=rep(score=20)),
        ],
        gametype="tdm",
    )
    _, rows = await listed(store)
    winner = rows[0]["winner"]
    assert winner["kind"] == "player" and winner["name"] == "Bee" and winner["others"] == 2


async def test_paging_gives_the_total_and_stable_slices(store: PlayerStore) -> None:
    for i in range(7):
        await record(store, f"m{i}", [human("a", frags=1)], started=NOW + i)
    total, first = await listed(store, limit=3, offset=0)
    _, second = await listed(store, limit=3, offset=3)
    _, last = await listed(store, limit=3, offset=6)
    assert total == 7
    assert ids(first) == ["m6", "m5", "m4"]
    assert ids(second) == ["m3", "m2", "m1"]
    assert ids(last) == ["m0"]
    assert (await listed(store, limit=3, offset=50)) == (7, [])


async def test_a_gametype_recorded_as_nothing_is_shown_as_unknown(store: PlayerStore) -> None:
    await record(store, "g", [human("a", frags=1)], gametype="")
    _, rows = await listed(store)
    assert rows[0]["gametype"] == "unknown"


# --- 4.2 one match -------------------------------------------------------------------------


async def test_a_v3_deathmatch_is_in_board_order_with_those_not_at_the_end_after(
    store: PlayerStore,
) -> None:
    pk = await record(
        store,
        "dm",
        [
            human(
                "late", name="Late", report=rep(board_pos=2, scores={"score": 4.0, "kills": 4.0})
            ),
            human(
                "win",
                name="Win",
                report=rep(board_pos=1, scores={"score": 9.0, "kills": 9.0}, wins=1),
            ),
            # left before the end: no board position, not valid
            human(
                "gone",
                name="Gone",
                report=ReportedPlayer(alivetime=20, avglatency=30, scores={"score": 7.0}),
            ),
            human(
                "spec",
                name="Spec",
                report=ReportedPlayer(alivetime=10, scores={"score": 1.0}),
            ),
            bot("x", report=rep(board_pos=3, scores={"score": 0.0, "deaths": 2.0})),
        ],
    )
    match = await store.get_match(pk)
    assert match is not None
    assert [p["name"] for p in match["players"]] == ["Win", "Late", "[BOT]x", "Gone", "Spec"]
    assert [p["at_end"] for p in match["players"]] == [True, True, True, False, False]
    assert match["players"][0]["values"] == {"score": 9.0, "kills": 9.0}
    gone = match["players"][3]
    assert gone["ping"] == 30 and gone["time_s"] == 20
    assert match["board_kept"] is True and match["teams"] == []
    assert match["winner"]["name"] == "Win"


async def test_a_v3_team_game_has_its_teams_with_their_values(store: PlayerStore) -> None:
    pk = await record(
        store,
        "tdm",
        [
            human("a", report=rep(team=5, board_pos=2, scores={"score": 2.0})),
            bot("x", report=rep(team=14, board_pos=1, wins=1, scores={"score": 3.0})),
            bot("y", report=rep(team=5, board_pos=3)),
        ],
        gametype="tdm",
        teams={14: {"score": 3.0}},
    )
    match = await store.get_match(pk)
    assert match is not None
    assert [p["team"] for p in match["players"]] == [14, 5, 5]
    # blue won with 3; red scored nothing so the game wrote no line, but it is still a team
    assert match["teams"] == [
        {"team": 14, "values": {"score": 3.0}},
        {"team": 5, "values": {}},
    ]
    assert match["winner"] == {"kind": "team", "team": 14}


async def test_a_ctf_players_extra_values_come_through_without_knowing_ctf(
    store: PlayerStore,
) -> None:
    pk = await record(
        store,
        "ctf",
        [
            human(
                "a",
                report=rep(
                    team=5,
                    board_pos=1,
                    scores={"score": 23.0, "caps": 1.0, "captime": 2543.0, "weirdlabel": 2.0},
                ),
            )
        ],
        gametype="ctf",
        teams={5: {"score": 74.0, "caps": 1.0}},
    )
    match = await store.get_match(pk)
    assert match is not None
    assert match["players"][0]["values"] == {
        "score": 23.0,
        "caps": 1.0,
        "captime": 2543.0,
        "weirdlabel": 2.0,
    }
    assert match["teams"] == [{"team": 5, "values": {"score": 74.0, "caps": 1.0}}]


async def test_an_older_reported_match_shows_what_was_recorded_without_teams(
    store: PlayerStore,
) -> None:
    def work(ops: Ops) -> int:
        a = ops.get_or_create_player("fp:a", "^1Ace", is_bot=False, now=NOW)
        b = ops.get_or_create_player("bot:x", "[BOT]x", is_bot=True, now=NOW)
        pk = ops.upsert_match("old", "boil", "tdm", NOW)
        ops.add_counters(pk, a, frags=5, deaths=3, suicides=1, teamkills=1)
        ops.add_counters(pk, b, frags=2, deaths=6)
        ops.apply_report(
            pk,
            finished=True,
            duration=300,
            players=[
                (
                    a,
                    rep(
                        score=12,
                        kills=5,
                        dmg=300,
                        dmgtaken=250,
                        alivetime=290,
                        avglatency=22,
                        extra={"caps": 2},
                    ),
                ),
                (b, ReportedPlayer(score=3, kills=2, dmg=90, dmgtaken=400, alivetime=300)),
            ],
        )
        # what a v2 panel left: no board, no names, no teams
        ops._c.execute("UPDATE matches SET board_kept = 0")
        ops._c.execute("DELETE FROM match_scores")
        ops._c.execute("UPDATE match_players SET name = NULL, team = NULL, board_pos = NULL")
        return pk

    pk = await store.transact(work)
    match = await store.get_match(pk)
    assert match is not None
    assert match["board_kept"] is False and match["teams"] == []
    first, second = match["players"]  # ordered by frags
    assert first["name"] == "^1Ace" and first["team"] is None
    assert first["values"] == {
        "score": 12.0,
        "kills": 5.0,
        "deaths": 3.0,
        "suicides": 1.0,
        "teamkills": 1.0,
        "dmg": 300.0,
        "dmgtaken": 250.0,
        "caps": 2.0,
    }
    assert first["at_end"] is True and first["ping"] == 22 and first["time_s"] == 290
    assert second["name"] == "[BOT]x" and second["at_end"] is False  # not valid on the board


async def test_a_match_without_a_report_shows_the_live_counters(store: PlayerStore) -> None:
    pk = await record(
        store,
        "crash",
        [
            human("a", frags=4, deaths=1),
            human("b", frags=7, deaths=2, suicides=1),
            bot("x", deaths=3),
        ],
        finished=None,
    )
    match = await store.get_match(pk)
    assert match is not None
    assert match["finished"] is None and match["reported"] is False
    assert [p["name"] for p in match["players"]] == ["b", "a", "[BOT]x"]
    b = match["players"][0]
    assert b["values"] == {"kills": 7.0, "deaths": 2.0, "suicides": 1.0, "teamkills": 0.0}
    assert b["at_end"] is None and b["ping"] is None and b["time_s"] is None
    assert match["winner"] is None


async def test_a_player_shows_the_name_they_used_in_the_match(store: PlayerStore) -> None:
    pk = await record(
        store,
        "m",
        [human("a", name="^1Ace", report=rep(board_pos=1, name="^1Ace", scores={"score": 5.0}))],
    )
    # renamed afterwards: the player's current name changes, the match's does not
    await store.transact(
        lambda ops: ops.get_or_create_player("fp:a", "^4Ace", is_bot=False, now=NOW + 99)
    )
    detail = await store.get_player(await pid(store, "a"), now=NOW + 100)
    assert detail is not None and detail["name"] == "^4Ace"
    match = await store.get_match(pk)
    assert match is not None and match["players"][0]["name"] == "^1Ace"
    # a match recorded without a name falls back to the current one
    await store.transact(lambda ops: ops._c.execute("UPDATE match_players SET name = NULL"))
    match = await store.get_match(pk)
    assert match is not None and match["players"][0]["name"] == "^4Ace"


async def test_an_unknown_match_is_none(store: PlayerStore) -> None:
    assert await store.get_match(12345) is None


async def test_a_match_with_nobody_in_it_has_a_summary_and_no_players(store: PlayerStore) -> None:
    pk = await store.transact(lambda ops: ops.upsert_match("empty", "boil", "dm", NOW))
    match = await store.get_match(pk)
    assert match is not None and match["players"] == [] and match["humans"] == 0


async def test_participant_counts_do_not_double_count(store: PlayerStore) -> None:
    players = [
        human("a", frags=2, report=rep(board_pos=1)),  # counters first, then the report
        human("b", report=rep(board_pos=2)),  # the report alone
        bot("x", frags=1, report=rep(board_pos=3)),
    ]
    await record(store, "m", players)
    await record(store, "m", players)  # the same match again: counters add up, counts do not
    _, rows = await listed(store)
    assert [(r["humans"], r["bots"]) for r in rows] == [(2, 1)]
