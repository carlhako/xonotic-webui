"""The player history database (player-stats spec): schema, writes and reads."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import AsyncIterator
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from xonotic_webui.players.store import (
    SCHEMA_VERSION,
    SORT_COLUMNS,
    Ops,
    PlayerStore,
    PlayerStoreError,
    ReportedPlayer,
    SchemaTooNewError,
)

NOW = 1_800_000_000


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[PlayerStore]:
    s = PlayerStore(tmp_path / "state" / "players.db")
    await s.open()
    yield s
    await s.close()


async def add_player(
    store: PlayerStore, key: str, name: str, *, is_bot: bool = False, now: int = NOW
) -> int:
    return await store.transact(
        lambda ops: ops.get_or_create_player(key, name, is_bot=is_bot, now=now)
    )


# --- schema and lifecycle ---------------------------------------------------------------


async def test_a_fresh_database_is_created_at_the_current_version(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "players.db"
    s = PlayerStore(path)
    await s.open()
    await s.close()
    assert path.is_file()
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 3
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def _take_back_to_v2(conn: sqlite3.Connection) -> None:
    """Remove what schema v3 added, leaving a database as a v2 panel wrote it."""
    for index in ("matches_started",):
        conn.execute(f"DROP INDEX {index}")
    for table in ("match_scores", "match_teams"):
        conn.execute(f"DROP TABLE {table}")
    for column in ("team", "board_pos", "name"):
        conn.execute(f"ALTER TABLE match_players DROP COLUMN {column}")
    for column in ("board_kept", "humans", "bots"):
        conn.execute(f"ALTER TABLE matches DROP COLUMN {column}")
    conn.execute("PRAGMA user_version = 2")


async def test_a_fresh_database_has_the_map_index(tmp_path: Path) -> None:
    path = tmp_path / "players.db"
    s = PlayerStore(path)
    await s.open()
    await s.close()
    with closing(sqlite3.connect(path)) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "matches_map" in names


async def test_a_v1_database_is_migrated_in_place_with_every_row_intact(tmp_path: Path) -> None:
    path = tmp_path / "players.db"
    first = PlayerStore(path)
    await first.open()
    pid = await add_player(first, "fp:abc", "^1Ace")

    def work(ops: Ops) -> None:
        m = ops.upsert_match("m1", "boil", "dm", NOW)
        ops.add_counters(m, pid, frags=7, deaths=2)
        ops.apply_report(
            m, finished=True, duration=60, players=[(pid, ReportedPlayer(scoreboard_valid=True))]
        )

    await first.transact(work)
    await first.close()
    with closing(sqlite3.connect(path)) as conn:  # take it back to what v1 wrote
        _take_back_to_v2(conn)
        conn.execute("DROP INDEX matches_map")
        conn.execute("PRAGMA user_version = 1")

    second = PlayerStore(path)
    await second.open()
    total, rows = await second.list_players(now=NOW)
    totals = await second.map_totals()
    await second.close()
    assert total == 1 and rows[0]["frags"] == 7 and rows[0]["matches"] == 1
    assert totals == {"boil": (1, 7, NOW)}
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "matches_map" in names


async def test_a_fresh_database_has_the_match_history_tables(tmp_path: Path) -> None:
    path = tmp_path / "players.db"
    s = PlayerStore(path)
    await s.open()
    await s.close()
    with closing(sqlite3.connect(path)) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        player_cols = {r[1] for r in conn.execute("PRAGMA table_info(match_players)")}
        match_cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
    assert {"match_scores", "match_teams"} <= tables
    assert "matches_started" in indexes
    assert {"team", "board_pos", "name"} <= player_cols
    assert {"board_kept", "humans", "bots"} <= match_cols


async def test_a_v2_database_is_migrated_in_place_with_every_row_intact(tmp_path: Path) -> None:
    path = tmp_path / "players.db"
    first = PlayerStore(path)
    await first.open()
    ace = await add_player(first, "fp:ace", "^1Ace")
    bot = await add_player(first, "bot:rex", "[BOT]Rex", is_bot=True)

    def work(ops: Ops) -> None:
        m = ops.upsert_match("m1", "boil", "dm", NOW)
        ops.add_counters(m, ace, frags=7, deaths=2)
        ops.add_counters(m, bot, frags=3)
        ops.apply_report(
            m,
            finished=True,
            duration=60,
            players=[
                (ace, ReportedPlayer(score=7, alivetime=55, wins=1, scoreboard_valid=True)),
                (bot, ReportedPlayer(score=3, alivetime=60, scoreboard_valid=True)),
            ],
        )

    await first.transact(work)
    before = await first.list_players(bots=True, now=NOW)
    await first.close()
    with closing(sqlite3.connect(path)) as conn:  # what a v2 panel left behind
        _take_back_to_v2(conn)

    second = PlayerStore(path)
    await second.open()
    after = await second.list_players(bots=True, now=NOW)
    totals = await second.map_totals()
    await second.close()
    assert after == before
    assert totals == {"boil": (1, 10, NOW)}
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        # nothing already stored was rewritten: no board, and no names, teams or positions
        assert conn.execute("SELECT board_kept FROM matches").fetchall() == [(0,)]
        # the participant counts are worked out for the matches already there
        assert conn.execute("SELECT humans, bots FROM matches").fetchall() == [(1, 1)]
        assert conn.execute(
            "SELECT team, board_pos, name FROM match_players ORDER BY player_id"
        ).fetchall() == [(None, None, None), (None, None, None)]
        assert conn.execute("SELECT COUNT(*) FROM match_scores").fetchone() == (0,)
        assert conn.execute("SELECT COUNT(*) FROM match_players").fetchone() == (2,)


async def test_reopening_keeps_the_data(tmp_path: Path) -> None:
    path = tmp_path / "players.db"
    first = PlayerStore(path)
    await first.open()
    pid = await add_player(first, "fp:abc", "^1Ace")
    await first.close()

    second = PlayerStore(path)
    await second.open()
    total, rows = await second.list_players(now=NOW)
    await second.close()
    assert total == 1 and rows[0]["id"] == pid and rows[0]["name"] == "^1Ace"


async def test_a_newer_schema_refuses_to_open_with_a_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "players.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA user_version = 99")
    s = PlayerStore(path)
    with pytest.raises(SchemaTooNewError, match="schema version 99"):
        await s.open()
    assert not s.is_open


async def test_using_a_closed_store_is_an_error(tmp_path: Path) -> None:
    s = PlayerStore(tmp_path / "players.db")
    with pytest.raises(PlayerStoreError):
        await s.list_players()


async def test_every_call_runs_on_the_worker_thread_not_the_event_loop(
    store: PlayerStore,
) -> None:
    seen: list[str] = []

    def probe(_ops: Ops) -> None:
        seen.append(threading.current_thread().name)

    await store.transact(probe)
    await store.transact(probe, write=False)
    assert seen and all(name.startswith("players-db") for name in seen)
    assert threading.current_thread().name not in seen


async def test_a_failing_transaction_rolls_back_entirely(store: PlayerStore) -> None:
    def boom(ops: Ops) -> None:
        ops.get_or_create_player("fp:half", "Half", is_bot=False, now=NOW)
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await store.transact(boom)
    total, _ = await store.list_players(bots=True, now=NOW)
    assert total == 0


async def test_revision_counts_committed_writes_only(store: PlayerStore) -> None:
    assert store.revision == 0
    await add_player(store, "fp:a", "A")
    assert store.revision == 1
    await store.list_players()
    assert store.revision == 1


# --- players, names and sessions -----------------------------------------------------------


async def test_the_same_key_is_one_player_and_names_become_aliases(store: PlayerStore) -> None:
    a = await add_player(store, "fp:abc", "^1Ace", now=NOW)
    b = await add_player(store, "fp:abc", "Zed", now=NOW + 60)
    assert a == b
    detail = await store.get_player(a, now=NOW + 100)
    assert detail is not None
    assert detail["name"] == "Zed"  # the most recently used
    assert {al["name"] for al in detail["aliases"]} == {"^1Ace", "Zed"}
    assert detail["first_seen"] == NOW and detail["last_seen"] == NOW + 60


async def test_a_name_noted_late_does_not_replace_a_more_recent_one(store: PlayerStore) -> None:
    pid = await add_player(store, "fp:abc", "Recent", now=NOW + 100)
    await store.transact(lambda ops: ops.upsert_alias(pid, "Older", NOW))
    detail = await store.get_player(pid, now=NOW + 200)
    assert detail is not None and detail["name"] == "Recent"
    assert {a["name"] for a in detail["aliases"]} == {"Recent", "Older"}
    # names within the same second: the one noted last wins
    await store.transact(lambda ops: ops.upsert_alias(pid, "Same second", NOW + 100))
    detail = await store.get_player(pid, now=NOW + 200)
    assert detail is not None and detail["name"] == "Same second"


async def test_different_keys_are_different_players(store: PlayerStore) -> None:
    a = await add_player(store, "fp:one", "Player")
    b = await add_player(store, "fp:two", "Player")
    assert a != b


async def test_a_name_key_merges_colour_variants(store: PlayerStore) -> None:
    # the recorder derives the key from the colour-stripped name; the store keeps both names
    a = await add_player(store, "name:ace", "^1Ace")
    b = await add_player(store, "name:ace", "^4Ace")
    assert a == b
    detail = await store.get_player(a, now=NOW)
    assert detail is not None and len(detail["aliases"]) == 2


async def test_sessions_open_close_and_add_to_time_on_server(store: PlayerStore) -> None:
    pid = await add_player(store, "fp:a", "A")
    sid = await store.transact(lambda ops: ops.open_session(pid, NOW))
    await store.transact(lambda ops: ops.close_session(sid, NOW + 600))
    # a second, still open session counts up to "now"
    await store.transact(lambda ops: ops.open_session(pid, NOW + 1000))
    _, rows = await store.list_players(now=NOW + 1100)
    assert rows[0]["time_on_server"] == 600 + 100
    detail = await store.get_player(pid, now=NOW + 1100)
    assert detail is not None and detail["sessions"] == 2


async def test_closing_a_session_twice_keeps_the_first_end(store: PlayerStore) -> None:
    pid = await add_player(store, "fp:a", "A")
    sid = await store.transact(lambda ops: ops.open_session(pid, NOW))
    await store.transact(lambda ops: ops.close_session(sid, NOW + 10))
    await store.transact(lambda ops: ops.close_session(sid, NOW + 99))
    _, rows = await store.list_players(now=NOW + 1000)
    assert rows[0]["time_on_server"] == 10


async def test_a_session_never_ends_before_it_started(store: PlayerStore) -> None:
    pid = await add_player(store, "fp:a", "A")
    sid = await store.transact(lambda ops: ops.open_session(pid, NOW + 50))
    await store.transact(lambda ops: ops.close_session(sid, NOW))
    _, rows = await store.list_players(now=NOW + 1000)
    assert rows[0]["time_on_server"] == 0


async def test_leftover_sessions_are_closed_at_the_players_last_seen(
    store: PlayerStore,
) -> None:
    pid = await add_player(store, "fp:a", "A", now=NOW)
    await store.transact(lambda ops: ops.open_session(pid, NOW))
    await store.transact(lambda ops: ops.touch_player(pid, NOW + 300))
    closed = await store.transact(lambda ops: ops.close_stale_sessions())
    assert closed == 1
    # an hour later the closed session still counts only up to last_seen
    _, rows = await store.list_players(now=NOW + 3600)
    assert rows[0]["time_on_server"] == 300
    assert await store.transact(lambda ops: ops.close_stale_sessions()) == 0


# --- matches, live counters and reports --------------------------------------------------------


async def test_live_counters_add_up_per_match(store: PlayerStore) -> None:
    pid = await add_player(store, "fp:a", "A")

    def work(ops: Ops) -> None:
        m1 = ops.upsert_match("m1", "atelier", "dm", NOW)
        m2 = ops.upsert_match("m2", "boil", "dm", NOW + 1)
        ops.add_counters(m1, pid, frags=2, deaths=1)
        ops.add_counters(m1, pid, frags=1, suicides=1, deaths=1)
        ops.add_counters(m2, pid, frags=4, teamkills=1)

    await store.transact(work)
    _, rows = await store.list_players(now=NOW)
    row = rows[0]
    assert (row["frags"], row["deaths"], row["suicides"], row["teamkills"]) == (7, 2, 1, 1)


async def test_upserting_a_match_twice_gives_one_row(store: PlayerStore) -> None:
    def work(ops: Ops) -> tuple[int, int]:
        return ops.upsert_match("m1", "", "", NOW), ops.upsert_match("m1", "atelier", "dm", NOW)

    a, b = await store.transact(work)
    assert a == b


async def test_a_report_adds_score_time_weapons_and_achievements(store: PlayerStore) -> None:
    pid = await add_player(store, "fp:a", "A")
    reported = ReportedPlayer(
        score=12,
        kills=11,
        alivetime=300.5,
        dmg=900,
        dmgtaken=400,
        wins=1,
        rank=1,
        avglatency=24,
        scoreboard_valid=True,
        joined=1,
        weapons={
            "vortex": {"hit": 100, "fired": 200, "cnt-hit": 5, "cnt-fired": 10, "frags": 3},
            "shotgun": {"hit": 50, "fired": 300},
        },
        achievements={"firstblood": 1},
        extra={"caps": 2},
    )

    def work(ops: Ops) -> None:
        m = ops.upsert_match("m1", "atelier", "dm", NOW)
        ops.add_counters(m, pid, frags=9, deaths=3)
        ops.apply_report(m, finished=True, duration=600, players=[(pid, reported)])

    await store.transact(work)
    _, rows = await store.list_players(now=NOW)
    row = rows[0]
    assert row["score"] == 12 and row["wins"] == 1 and row["matches"] == 1
    assert row["time_playing"] == 300.5
    assert row["frags"] == 9  # from the live counters, not the report's kills
    assert row["accuracy"] == pytest.approx(150 / 500)
    detail = await store.get_player(pid, now=NOW)
    assert detail is not None
    assert {w["weapon"]: w["fired"] for w in detail["weapons"]} == {"vortex": 200, "shotgun": 300}
    assert detail["achievements"] == [{"name": "firstblood", "count": 1}]
    assert detail["extra"] == [{"name": "caps", "value": 2}]
    assert detail["has_match_stats"] is True
    assert detail["avg_latency"] == 24


async def test_applying_the_same_report_twice_is_idempotent(store: PlayerStore) -> None:
    pid = await add_player(store, "fp:a", "A")
    reported = ReportedPlayer(
        score=5,
        alivetime=100,
        wins=1,
        scoreboard_valid=True,
        weapons={"vortex": {"hit": 10, "fired": 20}},
        achievements={"firstblood": 1},
    )

    def apply(ops: Ops) -> None:
        m = ops.upsert_match("m1", "atelier", "dm", NOW)
        ops.apply_report(m, finished=True, duration=60, players=[(pid, reported)])

    await store.transact(apply)
    before = await store.get_player(pid, now=NOW)
    await store.transact(apply)
    after = await store.get_player(pid, now=NOW)
    assert before == after
    assert after is not None and after["wins"] == 1 and after["matches"] == 1


def _rows_of(path: Path, sql: str) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(path)) as conn:
        return [tuple(r) for r in conn.execute(sql)]


async def test_a_report_keeps_team_position_name_scores_and_team_scores(
    store: PlayerStore,
) -> None:
    ace = await add_player(store, "fp:ace", "^1Ace")
    rex = await add_player(store, "bot:rex", "[BOT]Rex", is_bot=True)

    def work(ops: Ops) -> None:
        m = ops.upsert_match("m1", "boil", "tdm", NOW)
        ops.add_counters(m, ace, frags=4, name="^1Ace")
        ops.apply_report(
            m,
            finished=True,
            duration=90,
            players=[
                (
                    ace,
                    ReportedPlayer(
                        score=12,
                        wins=1,
                        scoreboard_valid=True,
                        team=5,
                        board_pos=1,
                        name="^1Ace",
                        scores={"score": 12.0, "kills": 4.0, "caps": 2.0},
                    ),
                ),
                (
                    rex,
                    ReportedPlayer(
                        score=3, team=14, board_pos=2, name="[BOT]Rex", scores={"score": 3.0}
                    ),
                ),
            ],
            teams={5: {"score": 12.0, "caps": 2.0}, 14: {"score": 3.0}},
        )

    await store.transact(work)
    path = store.path
    assert _rows_of(
        path,
        "SELECT player_id, team, board_pos, name FROM match_players ORDER BY player_id",
    ) == [(ace, 5, 1, "^1Ace"), (rex, 14, 2, "[BOT]Rex")]
    assert _rows_of(
        path, "SELECT player_id, label, value FROM match_scores ORDER BY player_id, label"
    ) == [
        (ace, "caps", 2.0),
        (ace, "kills", 4.0),
        (ace, "score", 12.0),
        (rex, "score", 3.0),
    ]
    assert _rows_of(path, "SELECT team, label, value FROM match_teams ORDER BY team, label") == [
        (5, "caps", 2.0),
        (5, "score", 12.0),
        (14, "score", 3.0),
    ]
    assert _rows_of(path, "SELECT board_kept FROM matches") == [(1,)]


async def test_a_match_without_a_report_has_no_board_kept(store: PlayerStore) -> None:
    pid = await add_player(store, "fp:a", "A")

    def work(ops: Ops) -> None:
        ops.add_counters(ops.upsert_match("m1", "atelier", "dm", NOW), pid, frags=1)

    await store.transact(work)
    assert _rows_of(store.path, "SELECT board_kept FROM matches") == [(0,)]


async def test_applying_a_v3_report_twice_leaves_identical_rows(store: PlayerStore) -> None:
    pid = await add_player(store, "fp:a", "A")
    reported = ReportedPlayer(
        score=5,
        wins=1,
        scoreboard_valid=True,
        team=14,
        board_pos=1,
        name="A",
        scores={"score": 5.0, "caps": 1.0},
    )

    def apply(ops: Ops) -> None:
        m = ops.upsert_match("m1", "atelier", "ctf", NOW)
        ops.apply_report(
            m, finished=True, duration=60, players=[(pid, reported)], teams={14: {"score": 5.0}}
        )

    await store.transact(apply)
    tables = (
        "SELECT * FROM match_players ORDER BY player_id",
        "SELECT * FROM match_scores ORDER BY label",
        "SELECT * FROM match_teams ORDER BY team, label",
        "SELECT * FROM matches",
    )
    before = [_rows_of(store.path, sql) for sql in tables]
    await store.transact(apply)
    assert [_rows_of(store.path, sql) for sql in tables] == before
    assert len(before[1]) == 2 and len(before[2]) == 1


async def test_a_second_report_replaces_a_players_scores_and_the_teams(
    store: PlayerStore,
) -> None:
    pid = await add_player(store, "fp:a", "A")

    def apply(scores: dict[str, float], teams: dict[int, dict[str, float]]) -> Any:
        def work(ops: Ops) -> None:
            m = ops.upsert_match("m1", "atelier", "tdm", NOW)
            ops.apply_report(
                m,
                finished=True,
                duration=60,
                players=[(pid, ReportedPlayer(team=5, scores=scores))],
                teams=teams,
            )

        return work

    await store.transact(apply({"score": 5.0, "caps": 1.0}, {5: {"score": 5.0}}))
    await store.transact(apply({"score": 8.0}, {5: {"score": 8.0}, 14: {"score": 1.0}}))
    assert _rows_of(store.path, "SELECT label, value FROM match_scores") == [("score", 8.0)]
    assert _rows_of(store.path, "SELECT team, value FROM match_teams ORDER BY team") == [
        (5, 8.0),
        (14, 1.0),
    ]


async def test_keeping_the_board_does_not_change_the_player_totals(
    store: PlayerStore, tmp_path: Path
) -> None:
    plain = PlayerStore(tmp_path / "plain" / "players.db")
    await plain.open()
    try:
        for target, kept in ((store, True), (plain, False)):
            pid = await add_player(target, "fp:a", "A")
            rex = await add_player(target, "bot:rex", "[BOT]Rex", is_bot=True)
            extra = (
                {"team": 5, "board_pos": 1, "name": "A", "scores": {"score": 9.0, "caps": 2.0}}
                if kept
                else {}
            )

            def work(
                ops: Ops, pid: int = pid, rex: int = rex, extra: Any = extra, kept: bool = kept
            ) -> None:
                m = ops.upsert_match("m1", "atelier", "dm", NOW)
                ops.add_counters(m, pid, frags=4, deaths=1, name="A")
                ops.apply_report(
                    m,
                    finished=True,
                    duration=60,
                    players=[
                        (
                            pid,
                            ReportedPlayer(
                                score=9,
                                kills=4,
                                alivetime=55,
                                dmg=100,
                                wins=1,
                                scoreboard_valid=True,
                                weapons={"vortex": {"hit": 3, "fired": 6}},
                                extra={"caps": 2},
                                **extra,
                            ),
                        ),
                        (rex, ReportedPlayer(score=2, alivetime=60, scoreboard_valid=True)),
                    ],
                    teams={5: {"score": 9.0}} if kept else None,
                )

            await target.transact(work)
        assert await store.list_players(bots=True, now=NOW) == await plain.list_players(
            bots=True, now=NOW
        )
        assert await store.map_totals() == await plain.map_totals()
    finally:
        await plain.close()


async def test_a_counter_name_is_replaced_by_a_later_one_and_then_by_the_reports(
    store: PlayerStore,
) -> None:
    pid = await add_player(store, "fp:a", "A")

    def counters(name: str) -> Any:
        def work(ops: Ops) -> None:
            ops.add_counters(ops.upsert_match("m1", "atelier", "dm", NOW), pid, frags=1, name=name)

        return work

    def report(name: str | None) -> Any:
        def work(ops: Ops) -> None:
            m = ops.upsert_match("m1", "atelier", "dm", NOW)
            ops.apply_report(
                m,
                finished=True,
                duration=60,
                players=[(pid, ReportedPlayer(scoreboard_valid=True, name=name))],
            )

        return work

    sql = "SELECT name FROM match_players"
    await store.transact(counters("^1Old"))
    assert _rows_of(store.path, sql) == [("^1Old",)]
    await store.transact(counters("^2New"))
    assert _rows_of(store.path, sql) == [("^2New",)]
    await store.transact(report("^3Report"))
    assert _rows_of(store.path, sql) == [("^3Report",)]
    # counts that arrive after the report do not take the name back, and a report with no
    # name keeps the one already there
    await store.transact(counters("^4Later"))
    assert _rows_of(store.path, sql) == [("^3Report",)]
    await store.transact(report(None))
    assert _rows_of(store.path, sql) == [("^3Report",)]


async def test_a_cut_short_match_is_not_a_finished_match_or_a_win(store: PlayerStore) -> None:
    pid = await add_player(store, "fp:a", "A")

    def work(ops: Ops) -> None:
        m = ops.upsert_match("m1", "atelier", "dm", NOW)
        ops.apply_report(
            m,
            finished=False,
            duration=30,
            players=[(pid, ReportedPlayer(alivetime=30, scoreboard_valid=True))],
        )

    await store.transact(work)
    _, rows = await store.list_players(now=NOW)
    assert rows[0]["matches"] == 0 and rows[0]["wins"] == 0 and rows[0]["time_playing"] == 30


async def test_a_player_with_only_live_counts_has_no_match_stats(store: PlayerStore) -> None:
    pid = await add_player(store, "fp:a", "A")

    def work(ops: Ops) -> None:
        ops.add_counters(ops.upsert_match("m1", "atelier", "dm", NOW), pid, frags=1)

    await store.transact(work)
    detail = await store.get_player(pid, now=NOW)
    assert detail is not None and detail["has_match_stats"] is False and detail["frags"] == 1


# --- reading -------------------------------------------------------------------------------


async def seed(store: PlayerStore) -> dict[str, int]:
    """Three humans and a bot with distinct figures for every sortable column."""
    specs = {
        "ann": ("fp:ann", "^1Ann", False, dict(frags=10, deaths=5, score=30, wins=2, alive=900)),
        "bob": ("fp:bob", "Bob", False, dict(frags=20, deaths=0, score=10, wins=0, alive=100)),
        "cy": ("fp:cy", "^4Cy^7Dee", False, dict(frags=5, deaths=10, score=50, wins=1, alive=500)),
        "bot": ("bot:rex", "[BOT]Rex", True, dict(frags=7, deaths=7, score=7, wins=0, alive=50)),
    }
    ids: dict[str, int] = {}

    def work(ops: Ops) -> None:
        match = ops.upsert_match("m1", "atelier", "dm", NOW)
        for index, (label, (key, name, is_bot, f)) in enumerate(specs.items()):
            pid = ops.get_or_create_player(key, name, is_bot=is_bot, now=NOW + index)
            ids[label] = pid
            ops.add_counters(match, pid, frags=f["frags"], deaths=f["deaths"])
            weapons = {"vortex": {"hit": f["frags"], "fired": 100}} if label != "cy" else None
            ops.apply_report(
                match,
                finished=True,
                duration=600,
                players=[
                    (
                        pid,
                        ReportedPlayer(
                            score=f["score"],
                            alivetime=f["alive"],
                            wins=f["wins"],
                            scoreboard_valid=True,
                            weapons=weapons,
                        ),
                    )
                ],
            )
            ops.open_session(pid, NOW - f["alive"])

    await store.transact(work)
    return ids


@pytest.mark.parametrize("sort", sorted(SORT_COLUMNS))
@pytest.mark.parametrize("descending", [True, False])
async def test_every_sort_column_orders_in_both_directions(
    store: PlayerStore, sort: str, descending: bool
) -> None:
    await seed(store)
    total, rows = await store.list_players(
        sort=sort, descending=descending, bots=True, now=NOW + 10
    )
    assert total == 4 and len(rows) == 4
    column = {
        "name": lambda r: r["name"],
        "kd": lambda r: r["kd"],
    }.get(sort, lambda r: r[sort])
    values = [column(r) for r in rows]
    comparable = [v for v in values if v is not None]
    if sort == "name":
        pass  # sorted by plain, case-folded text, checked separately below
    else:
        assert comparable == sorted(comparable, reverse=descending)
    # ties break on id so paging is stable
    again = await store.list_players(sort=sort, descending=descending, bots=True, now=NOW + 10)
    assert [r["id"] for r in again[1]] == [r["id"] for r in rows]


async def test_name_sort_ignores_colour_codes_and_case(store: PlayerStore) -> None:
    await seed(store)
    _, rows = await store.list_players(sort="name", descending=False, bots=True, now=NOW)
    # plain, case-folded text: "[bot]rex" sorts before the letters
    assert [r["name"] for r in rows] == ["[BOT]Rex", "^1Ann", "Bob", "^4Cy^7Dee"]


async def test_kd_with_no_deaths_is_the_frag_count(store: PlayerStore) -> None:
    ids = await seed(store)
    detail = await store.get_player(ids["bob"], now=NOW)
    assert detail is not None and detail["kd"] == 20.0
    detail = await store.get_player(ids["ann"], now=NOW)
    assert detail is not None and detail["kd"] == 2.0


async def test_accuracy_is_null_with_no_shots_and_sorts_last(store: PlayerStore) -> None:
    ids = await seed(store)
    detail = await store.get_player(ids["cy"], now=NOW)
    assert detail is not None and detail["accuracy"] is None
    for descending in (True, False):
        _, rows = await store.list_players(
            sort="accuracy", descending=descending, bots=True, now=NOW
        )
        assert rows[-1]["id"] == ids["cy"]


async def test_bots_are_excluded_unless_asked_for(store: PlayerStore) -> None:
    await seed(store)
    total, rows = await store.list_players(now=NOW)
    assert total == 3 and not any(r["is_bot"] for r in rows)
    total, rows = await store.list_players(bots=True, now=NOW)
    assert total == 4 and any(r["is_bot"] for r in rows)


async def test_search_matches_any_alias_ignoring_colour_and_case(store: PlayerStore) -> None:
    ids = await seed(store)
    await store.transact(lambda ops: ops.upsert_alias(ids["ann"], "^2Ace^7Pilot", NOW + 100))
    # the player's shown name is now "AcePilot"; the old name still finds them
    total, rows = await store.list_players(query="ann", now=NOW)
    assert total == 1 and rows[0]["id"] == ids["ann"] and rows[0]["name"] == "^2Ace^7Pilot"
    total, rows = await store.list_players(query="ACEpilot", now=NOW)
    assert [r["id"] for r in rows] == [ids["ann"]]
    # colour codes in the search itself do not matter
    total, rows = await store.list_players(query="^1Bo", now=NOW)
    assert [r["id"] for r in rows] == [ids["bob"]]
    total, rows = await store.list_players(query="dee", now=NOW)
    assert [r["id"] for r in rows] == [ids["cy"]]


async def test_search_treats_wildcards_literally(store: PlayerStore) -> None:
    await add_player(store, "fp:a", "100%_sure")
    await add_player(store, "fp:b", "plain")
    total, rows = await store.list_players(query="%", now=NOW)
    assert total == 1 and rows[0]["name"] == "100%_sure"
    total, _ = await store.list_players(query="_", now=NOW)
    assert total == 1
    total, _ = await store.list_players(query="\\", now=NOW)
    assert total == 0


async def test_paging_returns_the_total_and_stable_slices(store: PlayerStore) -> None:
    for i in range(7):
        await add_player(store, f"fp:{i}", f"P{i}")
    total, first = await store.list_players(sort="name", descending=False, limit=3, now=NOW)
    _, second = await store.list_players(sort="name", descending=False, limit=3, offset=3, now=NOW)
    _, last = await store.list_players(sort="name", descending=False, limit=3, offset=6, now=NOW)
    assert total == 7
    assert [r["name"] for r in first + second + last] == [f"P{i}" for i in range(7)]


async def test_an_unknown_player_is_none(store: PlayerStore) -> None:
    assert await store.get_player(424242, now=NOW) is None


async def test_no_ip_address_is_ever_stored(store: PlayerStore, tmp_path: Path) -> None:
    await seed(store)
    await store.close()
    raw = (tmp_path / "state" / "players.db").read_bytes()
    assert b"127.0.0.1" not in raw


async def test_a_large_database_lists_a_page_quickly(store: PlayerStore) -> None:
    def fill(ops: Ops) -> None:
        match = ops.upsert_match("big", "atelier", "dm", NOW)
        for i in range(20_000):
            pid = ops.get_or_create_player(f"fp:{i:06d}", f"Player {i}", is_bot=False, now=NOW)
            ops.open_session(pid, NOW - 600)
            ops.add_counters(match, pid, frags=i % 50, deaths=i % 7)

    await store.transact(fill)
    for sort in ("frags", "name", "time_on_server"):
        started = time.perf_counter()
        total, rows = await store.list_players(sort=sort, limit=50, now=NOW)
        elapsed = time.perf_counter() - started
        assert total == 20_000 and len(rows) == 50
        assert elapsed < 0.1, f"{sort}: {elapsed:.3f}s"


# --- per-map totals and details (design D1) -----------------------------------------------


def _play(
    ops: Ops,
    match_id: str,
    map_name: str,
    gametype: str,
    started_at: int,
    frags: dict[int, int],
    *,
    finished: bool | None,
) -> int:
    """A match with the live frags of each player; ``finished=None`` means no report yet."""
    match = ops.upsert_match(match_id, map_name, gametype, started_at)
    for pid, n in frags.items():
        ops.add_counters(match, pid, frags=n)
    if finished is not None:
        ops.apply_report(match, finished=finished, duration=60, players=[])
    return match


async def test_a_finished_match_counts_as_played_with_its_frags(store: PlayerStore) -> None:
    a = await add_player(store, "fp:a", "A")
    b = await add_player(store, "fp:b", "B")
    await store.transact(
        lambda ops: _play(ops, "m1", "boil", "dm", NOW, {a: 5, b: 3}, finished=True)
    )
    assert await store.map_totals() == {"boil": (1, 8, NOW)}


async def test_a_cut_short_match_adds_frags_and_last_played_but_not_played(
    store: PlayerStore,
) -> None:
    a = await add_player(store, "fp:a", "A")

    def work(ops: Ops) -> None:
        _play(ops, "m1", "boil", "dm", NOW, {a: 5}, finished=True)
        _play(ops, "m2", "boil", "dm", NOW + 100, {a: 4}, finished=False)

    await store.transact(work)
    assert await store.map_totals() == {"boil": (1, 9, NOW + 100)}


async def test_a_bots_frags_are_in_the_map_total(store: PlayerStore) -> None:
    bot = await add_player(store, "bot:1", "Bot", is_bot=True)
    await store.transact(lambda ops: _play(ops, "m1", "boil", "dm", NOW, {bot: 6}, finished=True))
    assert await store.map_totals() == {"boil": (1, 6, NOW)}


async def test_a_finished_match_with_no_participant_is_not_played(store: PlayerStore) -> None:
    await store.transact(lambda ops: _play(ops, "m1", "boil", "dm", NOW, {}, finished=True))
    assert await store.map_totals() == {}
    detail = await store.map_detail("boil")
    assert detail["played"] == 0 and detail["last_played"] is None


async def test_a_map_with_only_unreported_matches_has_frags_but_no_played(
    store: PlayerStore,
) -> None:
    a = await add_player(store, "fp:a", "A")
    await store.transact(lambda ops: _play(ops, "m1", "boil", "dm", NOW, {a: 2}, finished=None))
    assert await store.map_totals() == {"boil": (0, 2, NOW)}
    detail = await store.map_detail("boil")
    assert detail["played"] == 0 and detail["cut_short"] == 0 and detail["frags"] == 2


async def test_maps_do_not_mix(store: PlayerStore) -> None:
    a = await add_player(store, "fp:a", "A")

    def work(ops: Ops) -> None:
        _play(ops, "m1", "boil", "dm", NOW, {a: 5}, finished=True)
        _play(ops, "m2", "boil", "dm", NOW + 10, {a: 1}, finished=True)
        _play(ops, "m3", "atelier", "dm", NOW + 20, {a: 7}, finished=True)

    await store.transact(work)
    assert await store.map_totals() == {"boil": (2, 6, NOW + 10), "atelier": (1, 7, NOW + 20)}


async def test_map_detail_counts_times_and_gametypes(store: PlayerStore) -> None:
    a = await add_player(store, "fp:a", "A")

    def work(ops: Ops) -> None:
        _play(ops, "m1", "boil", "dm", NOW, {a: 5}, finished=True)
        _play(ops, "m2", "boil", "ctf", NOW + 50, {a: 2}, finished=True)
        _play(ops, "m3", "boil", "dm", NOW + 80, {a: 1}, finished=True)
        _play(ops, "m4", "boil", "", NOW + 90, {a: 1}, finished=True)
        _play(ops, "m5", "boil", "dm", NOW + 100, {a: 4}, finished=False)
        _play(ops, "m6", "atelier", "dm", NOW + 200, {a: 9}, finished=True)

    await store.transact(work)
    detail = await store.map_detail("boil")
    assert detail["played"] == 4 and detail["cut_short"] == 1 and detail["frags"] == 13
    assert detail["first_played"] == NOW and detail["last_played"] == NOW + 100
    # cut-short matches are not in the per-gametype list; unrecorded gametype is "unknown"
    assert detail["gametypes"] == [
        {"gametype": "dm", "played": 2},
        {"gametype": "ctf", "played": 1},
        {"gametype": "unknown", "played": 1},
    ]


async def test_top_fraggers_sum_across_matches_and_order_by_frags_then_name(
    store: PlayerStore,
) -> None:
    zed = await add_player(store, "fp:z", "Zed")
    amy = await add_player(store, "fp:a", "^1Amy")
    bot = await add_player(store, "bot:1", "Bot", is_bot=True)
    cat = await add_player(store, "fp:c", "Cat")

    def work(ops: Ops) -> None:
        _play(ops, "m1", "boil", "dm", NOW, {zed: 4, amy: 4, bot: 20, cat: 1}, finished=True)
        _play(ops, "m2", "boil", "dm", NOW + 1, {zed: 6, cat: 5}, finished=True)

    await store.transact(work)
    top = (await store.map_detail("boil"))["top_fraggers"]
    assert [(t["name"], t["frags"], t["is_bot"]) for t in top] == [
        ("Bot", 20, True),
        ("Zed", 10, False),
        ("Cat", 6, False),
        ("^1Amy", 4, False),
    ]
    assert top[0]["player_id"] == bot


async def test_top_fraggers_are_cut_to_ten(store: PlayerStore) -> None:
    def work(ops: Ops) -> None:
        pids = {
            ops.get_or_create_player(f"fp:{i:02d}", f"P{i:02d}", is_bot=False, now=NOW): i
            for i in range(12)
        }
        _play(ops, "m1", "boil", "dm", NOW, pids, finished=True)

    await store.transact(work)
    top = (await store.map_detail("boil"))["top_fraggers"]
    assert len(top) == 10
    assert [t["frags"] for t in top] == list(range(11, 1, -1))


async def test_an_unplayed_map_has_zero_details(store: PlayerStore) -> None:
    assert await store.map_detail("never") == {
        "played": 0,
        "cut_short": 0,
        "frags": 0,
        "first_played": None,
        "last_played": None,
        "gametypes": [],
        "top_fraggers": [],
    }
