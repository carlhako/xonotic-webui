"""The player recorder: identity, counting, sessions, reports and flushing.

Most tests drive the recorder with event lines and a stand-in console whose ``who`` reply
the test controls (``Rig``); the end-to-end ones run the real supervisor against the fake
server (see ``test_player_recorder_e2e.py``).
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from xonotic_webui.console.console import InternalQueryError
from xonotic_webui.players.recorder import PlayerRecorder
from xonotic_webui.players.store import PlayerStore
from xonotic_webui.players.who import WhoReplyCollector, WhoRow
from xonotic_webui.supervisor import NotRunningError, RunState

FIXTURES = Path(__file__).parent / "fixtures" / "xonotic"
T0 = 1_800_000_000


def fixture_lines(name: str) -> list[str]:
    return (FIXTURES / name).read_text().splitlines()


class StubSupervisor:
    def __init__(self) -> None:
        self.sinks: list[Callable[[str], None]] = []
        self.state_listeners: list[Callable[[RunState, RunState], None]] = []

    def add_line_sink(self, sink: Callable[[str], None]) -> None:
        self.sinks.append(sink)

    def subscribe_state(self, listener: Callable[[RunState, RunState], None]) -> None:
        self.state_listeners.append(listener)

    def set_state(self, to: RunState) -> None:
        for listener in self.state_listeners:
            listener(RunState.RUNNING, to)


class StubConsole:
    """Answers ``who`` from ``fingerprints`` (slot -> key), or fails as set."""

    def __init__(self) -> None:
        self.fingerprints: dict[int, str | None] = {}
        self.error: Exception | None = None
        self.delay = 0.0
        self.queries: list[str] = []

    async def query(
        self, command: str, collector: WhoReplyCollector, **_: Any
    ) -> WhoReplyCollector:
        self.queries.append(command)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        for ent, fp in self.fingerprints.items():
            collector.rows[ent] = WhoRow(ent, fp)
        return collector


class Clock:
    def __init__(self) -> None:
        self.now = float(T0)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Rig:
    def __init__(self, tmp_path: Path, **kwargs: Any) -> None:
        self.sup = StubSupervisor()
        self.console = StubConsole()
        self.clock = Clock()
        self.store = PlayerStore(tmp_path / "players.db")
        self.recorder = PlayerRecorder(
            self.sup,  # type: ignore[arg-type]
            self.console,  # type: ignore[arg-type]
            self.store,
            clock=self.clock,
            flush_interval=kwargs.pop("flush_interval", 3600.0),
            lookup_delay=kwargs.pop("lookup_delay", 0.01),
            **kwargs,
        )

    async def start(self) -> None:
        await self.recorder.start()

    def feed(self, *lines: str) -> None:
        for line in lines:
            for sink in self.sup.sinks:
                sink(line)

    async def settle(self) -> None:
        """Let the lookup run, then write everything pending."""
        for _ in range(3):
            await asyncio.sleep(0.05)
        await self.recorder.flush()

    def players(self) -> list[dict[str, Any]]:
        return [r for r in _rows(self.store.path, "SELECT * FROM players ORDER BY id")]

    def rows(self, sql: str) -> list[dict[str, Any]]:
        return _rows(self.store.path, sql)


def _rows(path: Path, sql: str) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql)]


@pytest.fixture
async def rig(tmp_path: Path) -> AsyncIterator[Callable[..., Rig]]:
    made: list[Rig] = []

    def make(**kwargs: Any) -> Rig:
        r = Rig(tmp_path / f"r{len(made)}", **kwargs)
        made.append(r)
        return r

    yield make
    for r in made:
        await r.recorder.aclose()


async def started(make: Callable[..., Rig], **kwargs: Any) -> Rig:
    r = make(**kwargs)
    await r.start()
    return r


MATCH = "^7:gamestart:dm_atelier:0.100.1"
FP_A = "AAAAfingerprintA+/AAAAAAAAAAAAAAAAAAAAAAAAA="
FP_B = "BBBBfingerprintB+/BBBBBBBBBBBBBBBBBBBBBBBBB="


def join(pid: int, ent: int, name: str, *, bot: bool = False) -> str:
    return f"^7:join:{pid}:{ent}:{'bot' if bot else '127.0.0.1'}:{name}"


# --- 5.1 identity ---------------------------------------------------------------------------


async def test_a_human_with_a_key_is_recorded_under_it(rig: Callable[..., Rig]) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_A}
    r.feed(MATCH, join(1, 1, "^1Spike^7Tester"))
    await r.settle()
    (player,) = r.players()
    assert player["key"] == f"fp:{FP_A}" and player["is_bot"] == 0
    assert player["name"] == "^1Spike^7Tester"
    assert r.console.queries == ['sv_cmd who "|"']


async def test_the_same_key_under_a_new_name_is_the_same_player(rig: Callable[..., Rig]) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_A}
    r.feed(MATCH, join(1, 1, "Old Name"), "^7:part:1")
    await r.settle()
    r.feed(join(2, 1, "New Name"))
    await r.settle()
    (player,) = r.players()
    assert player["name"] == "New Name"
    aliases = {a["name"] for a in r.rows("SELECT name FROM aliases")}
    assert aliases == {"Old Name", "New Name"}


async def test_a_rename_during_play_is_recorded(rig: Callable[..., Rig]) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_A}
    r.feed(MATCH, join(1, 1, "First"), "^7:name:1:Second", "^7:name:1:^1Third")
    await r.settle()
    (player,) = r.players()
    assert player["name"] == "^1Third"
    assert {a["name"] for a in r.rows("SELECT name FROM aliases")} == {"First", "Second", "^1Third"}


async def test_two_keys_with_one_name_are_two_players(rig: Callable[..., Rig]) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_A, 2: FP_B}
    r.feed(MATCH, join(1, 1, "Player"), join(2, 2, "Player"))
    await r.settle()
    assert len(r.players()) == 2


async def test_players_without_a_key_are_identified_by_their_plain_name(
    rig: Callable[..., Rig],
) -> None:
    r = await started(rig)
    r.console.fingerprints = {}  # the server reports none
    r.feed(MATCH, join(1, 1, "Player"), join(2, 2, "Player"), join(3, 3, "^1Ace"))
    await r.settle()
    r.feed("^7:part:3", join(4, 3, "^4Ace"))
    await r.settle()
    keys = sorted(p["key"] for p in r.players())
    assert keys == ["name:ace", "name:player"]


async def test_a_hidden_or_empty_fingerprint_falls_back_to_the_name(
    rig: Callable[..., Rig],
) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: None}
    r.feed(MATCH, join(1, 1, "Anon"))
    await r.settle()
    assert r.players()[0]["key"] == "name:anon"


async def test_a_failed_lookup_identifies_by_name_for_that_visit(rig: Callable[..., Rig]) -> None:
    r = await started(rig)
    r.console.error = InternalQueryError("no reply in time")
    r.feed(MATCH, join(1, 1, "^2Slow"))
    await r.settle()
    assert r.players()[0]["key"] == "name:slow"
    # a later visit that gets an answer is a different identity: merging is out of scope
    r.console.error = None
    r.console.fingerprints = {2: FP_A}
    r.feed("^7:part:1", join(2, 2, "^2Slow"))
    await r.settle()
    assert sorted(p["key"] for p in r.players()) == [f"fp:{FP_A}", "name:slow"]


async def test_a_lookup_while_the_server_stops_falls_back_to_the_name(
    rig: Callable[..., Rig],
) -> None:
    r = await started(rig)
    r.console.error = NotRunningError("the server is not running")
    r.feed(MATCH, join(1, 1, "Gone"))
    await r.settle()
    assert r.players()[0]["key"] == "name:gone"


async def test_a_burst_of_joins_is_one_query(rig: Callable[..., Rig]) -> None:
    r = await started(rig, lookup_delay=0.05)
    r.console.fingerprints = {1: FP_A, 2: FP_B}
    r.feed(MATCH, join(1, 1, "A"), join(2, 2, "B"), join(3, 3, "[BOT]x", bot=True))
    await r.settle()
    assert len(r.console.queries) == 1  # bots are never looked up
    assert sorted(p["key"] for p in r.players()) == ["bot:[bot]x", f"fp:{FP_A}", f"fp:{FP_B}"]


async def test_bots_are_recorded_as_bots_by_name(rig: Callable[..., Rig]) -> None:
    r = await started(rig)
    r.feed(MATCH, join(1, 1, "^1[BOT]Eureka", bot=True))
    await r.settle()
    (player,) = r.players()
    assert player["is_bot"] == 1 and player["key"] == "bot:[bot]eureka"
    assert r.console.queries == []


async def test_no_ip_address_reaches_the_database(rig: Callable[..., Rig], tmp_path: Path) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_A}
    r.feed(MATCH, join(1, 1, "A"))
    await r.settle()
    await r.recorder.aclose()
    blob = b"".join(p.read_bytes() for p in r.store.path.parent.glob("players.db*"))
    assert b"127.0.0.1" not in blob


# --- 5.2 kills ------------------------------------------------------------------------------


def totals(r: Rig) -> dict[str, dict[str, int]]:
    rows = r.rows(
        "SELECT p.name AS name, SUM(mp.frags) AS frags, SUM(mp.deaths) AS deaths, "
        "SUM(mp.suicides) AS suicides, SUM(mp.teamkills) AS teamkills "
        "FROM match_players mp JOIN players p ON p.id = mp.player_id GROUP BY p.id"
    )
    return {row["name"]: row for row in rows}


async def test_frag_suicide_accident_and_team_kill_counting(rig: Callable[..., Rig]) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_A, 2: FP_B}
    r.feed(MATCH, join(1, 1, "A"), join(2, 2, "B"))
    await r.settle()
    r.feed(
        "^7:kill:frag:1:2:type=258:items=2-1:victimitems=2-1",  # A frags B
        "^7:kill:frag:1:2:type=258:items=2-1:victimitems=2-1",
        "^7:kill:suicide:2:2:type=KILL:items=2-1",  # B suicides
        "^7:kill:accident:1:1:type=HURTTRIGGER:items=2-1",  # A falls
        "^7:kill:tk:2:1:type=2:items=2-1:victimitems=2-1",  # B kills A's... teammate
    )
    await r.settle()
    t = totals(r)
    assert (t["A"]["frags"], t["A"]["deaths"], t["A"]["suicides"], t["A"]["teamkills"]) == (
        2,
        2,
        0,
        0,
    )
    assert (t["B"]["frags"], t["B"]["deaths"], t["B"]["suicides"], t["B"]["teamkills"]) == (
        0,
        3,
        1,
        1,
    )


async def test_a_frag_against_a_bot_counts_for_the_human(rig: Callable[..., Rig]) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_A}
    r.feed(MATCH, join(1, 1, "Human"), join(2, 2, "[BOT]Eureka", bot=True))
    await r.settle()
    r.feed("^7:kill:frag:1:2:type=258:items=2-1:victimitems=2-1")
    await r.settle()
    t = totals(r)
    assert t["Human"]["frags"] == 1 and t["[BOT]Eureka"]["deaths"] == 1


async def test_kills_before_the_lookup_completes_are_kept(rig: Callable[..., Rig]) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_A}
    r.console.delay = 0.3
    r.feed(MATCH, join(1, 1, "Quick"), join(2, 2, "[BOT]b", bot=True))
    r.feed(
        "^7:kill:frag:1:2:type=258:items=2-1:victimitems=2-1",
        "^7:kill:frag:2:1:type=258:items=2-1:victimitems=2-1",
    )
    await r.recorder.flush()  # nothing can be placed yet: the key is unknown
    assert totals(r).get("Quick") is None
    await asyncio.sleep(0.5)
    await r.recorder.flush()
    t = totals(r)
    assert (t["Quick"]["frags"], t["Quick"]["deaths"]) == (1, 1)


async def test_unknown_player_ids_are_ignored(rig: Callable[..., Rig]) -> None:
    r = await started(rig)
    r.feed(MATCH, "^7:kill:frag:7:8:type=1:items=2-1", "^7:part:9", "^7:name:9:Ghost")
    await r.settle()
    assert r.players() == []


# --- 5.3 sessions ----------------------------------------------------------------------------


def sessions(r: Rig) -> list[tuple[int, int | None]]:
    return [
        (s["started_at"] - T0, None if s["ended_at"] is None else s["ended_at"] - T0)
        for s in r.rows("SELECT * FROM sessions ORDER BY id")
    ]


async def test_a_session_runs_from_join_to_part(rig: Callable[..., Rig]) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_A}
    r.feed(MATCH, join(1, 1, "A"))
    await r.settle()
    r.clock.advance(300)
    r.feed("^7:part:1")
    await r.settle()
    assert sessions(r) == [(0, 300)]


async def test_a_map_change_does_not_end_a_session_when_the_slot_rejoins(
    rig: Callable[..., Rig],
) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_A}
    r.feed(MATCH, join(1, 1, "A"))
    await r.settle()
    r.clock.advance(100)
    r.feed("^7:gamestart:dm_boil:0.100.2")  # the map changes ...
    r.clock.advance(5)
    r.feed(join(1, 1, "A"))  # ... and the client re-joins with a new id
    await r.settle()
    r.clock.advance(50)
    r.feed("^7:part:1")
    await r.settle()
    assert sessions(r) == [(0, 155)]


async def test_a_different_key_on_the_slot_ends_the_session_at_the_map_change(
    rig: Callable[..., Rig],
) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_A}
    r.feed(MATCH, join(1, 1, "A"))
    await r.settle()
    r.clock.advance(100)
    r.feed("^7:gamestart:dm_boil:0.100.2")
    r.clock.advance(10)
    r.console.fingerprints = {1: FP_B}
    r.feed(join(1, 1, "B"))
    await r.settle()
    assert sorted(sessions(r)) == [(0, 100), (110, None)]


async def test_a_client_that_never_rejoins_ends_at_the_map_change_after_the_grace(
    rig: Callable[..., Rig],
) -> None:
    r = await started(rig, rejoin_grace=120)
    r.console.fingerprints = {1: FP_A}
    r.feed(MATCH, join(1, 1, "A"))
    await r.settle()
    r.clock.advance(100)
    r.feed("^7:gamestart:dm_boil:0.100.2")
    r.clock.advance(60)
    await r.recorder.flush()
    assert sessions(r) == [(0, None)]  # still waiting for the client
    r.clock.advance(100)
    await r.recorder.flush()
    assert sessions(r) == [(0, 100)]  # ended when the map changed


async def test_stopping_the_server_ends_every_session_at_that_moment(
    rig: Callable[..., Rig],
) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_A, 2: FP_B}
    r.feed(MATCH, join(1, 1, "A"), join(2, 2, "B"), join(3, 3, "[BOT]x", bot=True))
    await r.settle()
    r.clock.advance(500)
    r.sup.set_state(RunState.STOPPED)  # a crash looks the same: the state goes to stopped
    await r.settle()
    assert sorted(sessions(r)) == [(0, 500)] * 3
    # the next run starts clean
    r.clock.advance(60)
    r.feed(MATCH)
    r.sup.set_state(RunState.STARTING)
    await r.settle()
    assert len(sessions(r)) == 3


async def test_a_leftover_session_is_closed_at_start_up_at_the_last_seen_time(
    tmp_path: Path,
) -> None:
    rig_a = Rig(tmp_path / "x")
    await rig_a.start()
    rig_a.console.fingerprints = {1: FP_A}
    rig_a.feed(MATCH, join(1, 1, "A"))
    await rig_a.settle()
    rig_a.clock.advance(40)
    rig_a.feed("^7:kill:frag:1:1:type=1:items=2-1")  # activity, so a flush touches the player
    rig_a.clock.advance(40)
    await rig_a.recorder.flush()
    # the panel dies here: no clean shutdown, so the session is still open in the file
    assert sessions(rig_a) == [(0, None)]
    await rig_a.store.close()

    later = Rig(tmp_path / "x")
    later.clock.advance(100_000)  # a long outage
    await later.start()
    assert sessions(later) == [(0, 80)]  # not counted while the panel was not running
    await later.recorder.aclose()


async def test_a_panel_shutdown_closes_open_sessions(rig: Callable[..., Rig]) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_A}
    r.feed(MATCH, join(1, 1, "A"))
    await r.settle()
    r.clock.advance(70)
    await r.recorder.aclose()
    assert sessions(r) == [(0, 70)]


# --- real-capture driven sessions ------------------------------------------------------------


def who_fingerprints(lines: list[str]) -> dict[int, str]:
    """slot -> fingerprint for the humans in the first who reply of a capture."""
    collector = WhoReplyCollector()
    for line in lines:
        collector.feed(line)
    return {ent: row.fingerprint for ent, row in collector.rows.items() if row.fingerprint}


async def test_one_session_across_a_real_map_change(rig: Callable[..., Rig]) -> None:
    lines = fixture_lines("session_map_change_rejoin.txt")
    r = await started(rig)
    r.console.fingerprints = who_fingerprints(lines)
    assert r.console.fingerprints  # the human's slot and key come from the capture
    first = lines.index(next(line for line in lines if ":gamestart:" in line))
    for index, line in enumerate(lines[first:]):
        r.feed(line)
        if index % 40 == 0:
            r.clock.advance(5)
            await asyncio.sleep(0.03)
    await r.settle()
    humans = [p for p in r.players() if not p["is_bot"]]
    assert len(humans) == 1
    human_sessions = r.rows(f"SELECT * FROM sessions WHERE player_id = {humans[0]['id']}")
    assert len(human_sessions) == 1  # one visit although the map changed with them connected


async def test_a_client_lost_while_the_next_map_loads_ends_at_the_map_change(
    rig: Callable[..., Rig],
) -> None:
    lines = fixture_lines("session_leave_during_map_change.txt")
    r = await started(rig, rejoin_grace=60)
    r.console.fingerprints = who_fingerprints(lines)
    first = lines.index(next(line for line in lines if ":gamestart:" in line))
    change = max(i for i, line in enumerate(lines) if ":gamestart:" in line)
    for line in lines[first:change]:
        r.feed(line)
        r.clock.advance(0.5)
    await r.settle()
    r.clock.advance(1)
    for line in lines[change:]:  # the map change, then the human is never seen again
        r.feed(line)
    changed_at = int(r.clock.now)
    r.clock.advance(200)
    await r.settle()
    human = next(p for p in r.players() if not p["is_bot"])
    (session,) = r.rows(f"SELECT * FROM sessions WHERE player_id = {human['id']}")
    assert session["ended_at"] == changed_at


# --- 5.4 reports -----------------------------------------------------------------------------

REPORT_MATCH = "^7:gamestart:dm_atelier:0.1791950428.917818"
FP_SPIKE = "UYmJXnCuUcu07skut12/ILC1F1Th7PZC6PxpWPTpjqo="  # the human in report_finished.txt


def report_session(r: Rig, *, human_part: bool = False) -> list[str]:
    """The joins that go with report_finished.txt, then the capture's match end."""
    lines = [
        REPORT_MATCH,
        join(1, 1, "^1Spike^7Tester"),
        join(2, 2, "[BOT]Death", bot=True),
        join(3, 3, "[BOT]Mystery", bot=True),
    ]
    if human_part:
        lines.append("^7:part:1")
    return lines + fixture_lines("report_finished.txt")


async def test_a_finished_match_records_the_figures_and_the_win(rig: Callable[..., Rig]) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_SPIKE}
    r.feed(*report_session(r))
    await r.settle()
    (match,) = r.rows("SELECT * FROM matches")
    assert match["match_id"] == "0.1791950428.917818"
    assert match["finished"] == 1 and match["reported"] == 1 and match["duration"] > 100
    human = next(p for p in r.players() if not p["is_bot"])
    (row,) = r.rows(f"SELECT * FROM match_players WHERE player_id = {human['id']}")
    assert row["alivetime"] > 0 and row["scoreboard_valid"] == 1 and row["score"] == -1
    assert row["suicides"] == 0  # live counters come only from :kill lines
    weapons = {
        w["weapon"]: w
        for w in r.rows(f"SELECT * FROM weapon_stats WHERE player_id = {human['id']}")
    }
    assert weapons["shotgun"]["cnt_fired"] == 22 and weapons["hagar"]["hit"] > 29
    winners = r.rows(
        "SELECT p.name FROM match_players mp JOIN players p ON p.id = mp.player_id "
        "WHERE mp.wins > 0"
    )
    assert [w["name"] for w in winners] == ["[BOT]Mystery"]
    achievements = r.rows("SELECT name FROM achievements")
    assert {a["name"] for a in achievements} == {"firstblood", "firstvictim"}


async def test_a_player_who_left_before_the_end_still_gets_their_row(
    rig: Callable[..., Rig],
) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_SPIKE}
    r.feed(*report_session(r, human_part=True))
    await r.settle()
    human = next(p for p in r.players() if not p["is_bot"])
    rows = r.rows(f"SELECT * FROM match_players WHERE player_id = {human['id']}")
    assert len(rows) == 1 and rows[0]["alivetime"] > 0


async def test_the_report_links_by_player_id_not_by_its_key(rig: Callable[..., Rig]) -> None:
    lines = fixture_lines("report_privacy_optout.txt")  # P player#1, no n
    r = await started(rig)
    r.console.fingerprints = {1: FP_A}
    r.feed(
        "^7:gamestart:dm_atelier:0.1791950880.130110",
        join(1, 1, "^5Private^7Pat"),
        join(2, 2, "[BOT]Resurrection", bot=True),
    )
    await r.settle()
    r.feed(*lines)
    await r.settle()
    human = next(p for p in r.players() if not p["is_bot"])
    assert human["key"] == f"fp:{FP_A}"  # identified by who, linked by id
    (row,) = r.rows(f"SELECT * FROM match_players WHERE player_id = {human['id']}")
    assert row["alivetime"] > 29 and row["reported"] == 1


async def test_a_cut_short_match_is_stored_unfinished_with_no_wins(
    rig: Callable[..., Rig],
) -> None:
    lines = fixture_lines("report_unfinished.txt")
    r = await started(rig)
    r.console.fingerprints = {1: FP_A}
    r.feed("^7:gamestart:dm_atelier:0.1791950647.489966", join(1, 1, "^2Map^7Changer"))
    await r.settle()
    r.feed(*lines)
    await r.settle()
    (match,) = r.rows("SELECT * FROM matches WHERE reported = 1")
    assert match["finished"] == 0
    assert r.rows("SELECT * FROM match_players WHERE wins > 0") == []
    human = next(p for p in r.players() if not p["is_bot"])
    (row,) = r.rows(f"SELECT * FROM match_players WHERE player_id = {human['id']}")
    assert row["alivetime"] > 30


async def test_a_report_for_a_match_the_panel_did_not_see_start_is_still_stored(
    rig: Callable[..., Rig],
) -> None:
    r = await started(rig)  # no :gamestart: and no :join: lines at all
    r.feed(*fixture_lines("report_finished.txt"))
    await r.settle()
    (match,) = r.rows("SELECT * FROM matches")
    assert match["finished"] == 1 and match["map"] == "atelier"
    keys = sorted(p["key"] for p in r.players())
    assert keys == ["bot:[bot]death", "bot:[bot]mystery", f"fp:{FP_SPIKE}"]
    human = next(p for p in r.players() if not p["is_bot"])
    assert human["name"] == "^1Spike^7Tester"
    assert r.rows("SELECT * FROM weapon_stats")


async def test_a_report_after_the_panel_started_mid_match_adopts_the_current_match(
    rig: Callable[..., Rig],
) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_SPIKE}
    r.feed(join(1, 1, "^1Spike^7Tester"))  # joined before we saw a :gamestart:
    await r.settle()
    r.feed("^7:kill:frag:1:1:type=1:items=2-1")
    r.feed(*fixture_lines("report_finished.txt"))
    await r.settle()
    (match,) = r.rows("SELECT * FROM matches")
    assert match["match_id"] == "0.1791950428.917818"
    human = next(p for p in r.players() if not p["is_bot"])
    (row,) = r.rows(f"SELECT * FROM match_players WHERE player_id = {human['id']}")
    assert row["deaths"] == 1 and row["alivetime"] > 0


async def test_the_same_report_twice_changes_nothing(rig: Callable[..., Rig]) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_SPIKE}
    r.feed(*report_session(r))
    await r.settle()
    before = r.rows("SELECT * FROM match_players ORDER BY match_pk, player_id")
    r.feed(*fixture_lines("report_finished.txt"))
    await r.settle()
    assert r.rows("SELECT * FROM match_players ORDER BY match_pk, player_id") == before
    assert len(r.rows("SELECT * FROM matches")) == 1


async def test_an_empty_report_stores_nothing(rig: Callable[..., Rig]) -> None:
    r = await started(rig)
    r.feed("^7:gamestart:dm_boil:0.5.5", "^7V 9", "^7G dm", "^7M boil", "^7I 0.5.5", "^7D 0", "^7")
    await r.settle()
    assert r.rows("SELECT * FROM matches") == []


async def test_report_lines_do_not_disturb_event_parsing(rig: Callable[..., Rig]) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_SPIKE}
    r.feed(*report_session(r))
    r.feed("^7:gamestart:dm_boil:0.5.5", join(1, 1, "^1Spike^7Tester"))
    await r.settle()
    human = next(p for p in r.players() if not p["is_bot"])
    assert len(r.rows(f"SELECT * FROM sessions WHERE player_id = {human['id']}")) == 1


# --- 5.5 flushing ----------------------------------------------------------------------------


async def test_counters_reach_the_database_within_one_interval(rig: Callable[..., Rig]) -> None:
    r = await started(rig, flush_interval=0.1)
    r.console.fingerprints = {1: FP_A}
    r.feed(MATCH, join(1, 1, "A"), join(2, 2, "[BOT]b", bot=True))
    await asyncio.sleep(0.4)
    r.feed("^7:kill:frag:1:2:type=1:items=2-1:victimitems=2-1")
    for _ in range(40):
        await asyncio.sleep(0.05)
        if totals(r).get("A", {}).get("frags") == 1:
            break
    assert totals(r)["A"]["frags"] == 1
    assert totals(r)["[BOT]b"]["deaths"] == 1


async def test_a_store_that_fails_is_retried_and_loses_nothing(
    rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_A}
    r.feed(MATCH, join(1, 1, "A"), join(2, 2, "[BOT]b", bot=True))
    await r.settle()
    original = r.store.transact
    broken = {"on": True}

    async def flaky(fn: Any, **kwargs: Any) -> Any:
        if broken["on"]:
            raise sqlite3.OperationalError("disk is full")
        return await original(fn, **kwargs)

    monkeypatch.setattr(r.store, "transact", flaky)
    r.feed("^7:kill:frag:1:2:type=1:items=2-1:victimitems=2-1")
    await r.recorder.flush()  # never raises
    assert "could not be written" in caplog.text
    broken["on"] = False
    await r.recorder.flush()
    assert totals(r)["A"]["frags"] == 1  # the failed write was kept and retried


async def test_shutdown_flushes_pending_counts(rig: Callable[..., Rig]) -> None:
    r = await started(rig)
    r.console.fingerprints = {1: FP_A}
    r.feed(MATCH, join(1, 1, "A"), join(2, 2, "[BOT]b", bot=True))
    await r.settle()
    r.feed("^7:kill:frag:1:2:type=1:items=2-1:victimitems=2-1")
    await r.recorder.aclose()
    assert totals(r)["A"]["frags"] == 1


async def test_a_store_that_cannot_open_turns_recording_off_quietly(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "players.db"
    path.mkdir()  # a directory where the file should be
    sup, console = StubSupervisor(), StubConsole()
    recorder = PlayerRecorder(sup, console, PlayerStore(path))  # type: ignore[arg-type]
    await recorder.start()
    assert recorder.enabled is False
    assert "could not be opened" in caplog.text
    for sink in sup.sinks:
        sink("^7:join:1:1:127.0.0.1:A")  # ignored, no error
    await recorder.aclose()
