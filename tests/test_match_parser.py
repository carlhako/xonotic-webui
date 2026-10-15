"""The live-match poll reply, scoreboard and clock, against real captures
(``tests/fixtures/xonotic/match_*``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from xonotic_webui.match.board import TEAM_COLORS, build_scoreboard, parse_labels
from xonotic_webui.match.clock import compute_clock, compute_score_limit
from xonotic_webui.match.reply import (
    MatchReply,
    MatchReplyCollector,
    parse_logscores_bots,
    parse_player_line,
    parse_team_line,
    poll_command,
)

FIXTURES = Path(__file__).parent / "fixtures" / "xonotic"


def fixture_lines(name: str) -> list[str]:
    return (FIXTURES / name).read_text().splitlines()


def collect(lines: list[str]) -> tuple[MatchReplyCollector, list[str]]:
    """Feed every line; return the collector and the lines it did *not* consume."""
    collector = MatchReplyCollector()
    left = [line for line in lines if not collector.feed(line)]
    return collector, left


# --- 2.1 the collector ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "match_dm_live.txt",
        "match_dm_spectator_live.txt",
        "match_tdm_live.txt",
        "match_ctf_live.txt",
        "match_intermission_live.txt",
    ],
)
def test_every_line_of_a_live_reply_is_consumed(name: str) -> None:
    collector, left = collect(fixture_lines(name))
    assert left == []
    assert collector.done


def test_the_reply_is_complete_after_stats_dumped_only() -> None:
    lines = fixture_lines("match_dm_live.txt")
    collector = MatchReplyCollector()
    for line in lines[:-1]:
        assert collector.feed(line)
    assert not collector.done
    assert collector.feed(lines[-1])
    assert collector.done
    assert collector.feed("^7more") is False  # nothing after the end is taken


def test_a_dm_reply_has_globals_cvars_status_and_dump() -> None:
    reply = collect(fixture_lines("match_dm_live.txt"))[0].reply
    assert reply.globals["time"] == pytest.approx(24.1334114)
    assert reply.globals["game_starttime"] == 16
    assert reply.globals["warmup_stage"] == 0
    assert reply.globals["intermission_running"] == 0
    assert reply.timelimit == 10
    assert reply.fraglimit == 30
    assert [(r.ent, r.bot, r.ping) for r in reply.status_rows] == [
        (1, False, 33),
        (2, True, 0),
        (3, True, 0),
    ]
    assert reply.dump is not None
    assert (reply.dump.gametype, reply.dump.map, reply.dump.time) == ("dm", "implosion", 24)
    assert len(reply.dump.players) == 3


def test_a_game_printed_score_dump_is_not_taken() -> None:
    """The game prints its own ``:scores:`` dump at match end; it stays on the console."""
    own = [
        "^7:scores:dm_trident:76",
        "^7:labels:player:score!!,,kills",
        "^7:player:see-labels:1,0,2:73:-1:3:Someone",
        "^7:end",
        "^7:gameover",
    ]
    collector = MatchReplyCollector()
    assert [collector.feed(line) for line in own] == [False] * 5
    assert collector.reply.dump is None


def test_an_unknown_global_is_consumed_and_recorded() -> None:
    lines = [
        "^7No global 'game_stopped' in server!",
        *fixture_lines("match_dm_live.txt"),
    ]
    collector, left = collect(lines)
    assert left == []
    assert collector.reply.unknown_globals == {"game_stopped"}
    assert "game_stopped" not in collector.reply.globals


def test_unrelated_lines_are_left_alone() -> None:
    lines = fixture_lines("match_dm_live.txt")
    noise = ["^7[BOT]Gator^1 was in the wrong place", "^7:kill:accident:2:2:type=HURTTRIGGER"]
    mixed = lines[:5] + noise + lines[5:]
    collector, left = collect(mixed)
    assert left == noise
    assert collector.done


def test_a_dump_with_no_players_is_still_a_dump() -> None:
    lines = [
        "^7time: 6.5",
        "^7game_starttime: 0",
        '^7"timelimit" is "10" ["0"]',
        "^7^7:status:dm_trident:7",
        "^7^7:labels:player:score!!,,kills",
        "^7^7:end",
        "^7^7stats dumped.",
    ]
    collector, left = collect(lines)
    assert left == []
    assert collector.reply.dump is not None
    assert collector.reply.dump.players == []


def test_no_dump_at_all_still_ends_the_reply() -> None:
    lines = ["^7time: 6.5", "^7game_starttime: 16", "^7^7stats dumped."]
    collector, left = collect(lines)
    assert left == [] and collector.done
    assert collector.reply.dump is None


def test_the_poll_line_raises_logscores_bots_only_around_the_dump() -> None:
    command = poll_command("0")
    parts = command.split("; ")
    assert parts[0] == "sv_logscores_bots 1"
    assert parts[-1] == "sv_logscores_bots 0"
    assert parts[-2] == "sv_cmd printstats"
    assert "prvm_global server game_starttime" in parts
    assert poll_command("1").endswith("sv_logscores_bots 1")


def test_logscores_bots_value_is_read_from_the_cvar_reply() -> None:
    assert parse_logscores_bots('"sv_logscores_bots" is "1" ["0"]') == "1"
    assert parse_logscores_bots('"sv_logscores_bots" is "0" ["0"]') == "0"
    assert parse_logscores_bots('"timelimit" is "10" ["0"]') is None


# --- 2.2 the dump --------------------------------------------------------------------------


def reply_of(name: str) -> MatchReply:
    return collect(fixture_lines(name))[0].reply


def test_dm_scoreboard_has_the_games_columns_in_the_games_order() -> None:
    reply = reply_of("match_dm_live.txt")
    board = build_scoreboard(reply.dump, reply.status_rows)
    assert board["available"] is True
    keys = [c["key"] for c in board["columns"]]
    assert keys == ["score", "kills", "deaths", "suicides", "dmg", "dmgtaken"]
    score = board["columns"][0]
    assert score["primary"] and not score["secondary"] and not score["lower_is_better"]
    deaths = board["columns"][2]
    assert deaths["lower_is_better"]
    # elo and rounds_pl are not shown, and neither are the unnamed columns
    assert "elo" not in keys and "rounds_pl" not in keys and "" not in keys


def test_dm_players_bots_ping_and_ents_come_from_the_status_reply() -> None:
    reply = reply_of("match_dm_live.txt")
    board = build_scoreboard(reply.dump, reply.status_rows)
    by_name = {p["plain_name"]: p for p in board["players"]}
    assert sorted(by_name) == ["[BOT]Delirium", "[BOT]Gator", "die😁😁😁"]
    human = by_name["die😁😁😁"]
    assert (human["bot"], human["ent"], human["ping"]) == (False, 1, 33)
    assert human["name"].startswith("^x0F0die")
    assert human["time_s"] == 20 and human["team"] is None
    assert by_name["[BOT]Gator"]["bot"] is True
    assert by_name["[BOT]Gator"]["ent"] == 2
    taken = by_name["[BOT]Gator"]["values"]
    assert taken["dmg"] == 0 and taken["dmgtaken"] == pytest.approx(15.430884)
    assert board["spectators"] == [] and board["teams"] == []


def test_a_spectator_is_listed_apart_without_scores() -> None:
    reply = reply_of("match_dm_spectator_live.txt")
    board = build_scoreboard(reply.dump, reply.status_rows)
    # both bots have 1 point: the tie goes to the name
    assert [p["plain_name"] for p in board["players"]] == ["[BOT]Delirium", "[BOT]Gator"]
    assert len(board["spectators"]) == 1
    spectator = board["spectators"][0]
    assert spectator["plain_name"] == "die😁😁😁"
    assert spectator["ent"] == 1 and spectator["bot"] is False
    assert "values" not in spectator


def test_tdm_reports_teams_with_colours_and_each_players_team() -> None:
    reply = reply_of("match_tdm_live.txt")
    board = build_scoreboard(reply.dump, reply.status_rows)
    assert {p["plain_name"]: p["team"] for p in board["players"]} == {
        "die😁😁😁": 5,
        "[BOT]Dominator": 5,
        "[BOT]Pegasus": 14,
    }
    assert board["teams"] == [
        {"team": 5, "color": "red", "values": {"score": 1}},
        {"team": 14, "color": "blue", "values": {"score": 0}},
    ]
    assert [c["key"] for c in board["columns"]][:2] == ["score", "kills"]
    assert "teamkills" in [c["key"] for c in board["columns"]]


def test_ctf_extra_columns_need_no_gametype_table() -> None:
    reply = reply_of("match_ctf_live.txt")
    board = build_scoreboard(reply.dump, reply.status_rows)
    columns = {c["key"]: c for c in board["columns"]}
    assert list(columns)[:3] == ["score", "caps", "fckills"]
    assert columns["score"]["primary"] and columns["caps"]["secondary"]
    assert columns["drops"]["lower_is_better"] and columns["captime"]["lower_is_better"]
    # the team's primary column is captures
    assert board["teams"] == [
        {"team": 5, "color": "red", "values": {"caps": 0, "score": 1}},
        {"team": 14, "color": "blue", "values": {"caps": 0, "score": 0}},
    ]
    assert len(board["spectators"]) == 0


def test_the_intermission_dump_still_lists_every_client() -> None:
    reply = reply_of("match_intermission_live.txt")
    board = build_scoreboard(reply.dump, reply.status_rows)
    assert len(board["players"]) == 2
    assert len(board["spectators"]) == 1


def test_players_are_sorted_by_primary_then_secondary_then_name() -> None:
    labels = ["score!!", "kills!", "deaths<", ""]
    lines = [
        "^7:status:dm_x:1",
        f"^7:labels:player:{','.join(labels)}",
        "^7:player:see-labels:5,1,0,0:10:-1:Zed",
        "^7:player:see-labels:12,0,0,0:10:-1:Mid",
        "^7:player:see-labels:5,3,0,0:10:-1:Low",
        "^7:player:see-labels:5,3,0,0:10:-1:amy",
        "^7:end",
        "^7stats dumped.",
    ]
    reply = collect(lines)[0].reply
    board = build_scoreboard(reply.dump, [])
    assert [p["plain_name"] for p in board["players"]] == ["Mid", "amy", "Low", "Zed"]


def test_lower_is_better_sorts_ascending() -> None:
    lines = [
        "^7:status:rc_x:1",
        "^7:labels:player:time<!!,laps",
        "^7:player:see-labels:90,2:10:-1:Slow",
        "^7:player:see-labels:45,2:10:-1:Fast",
        "^7:end",
        "^7stats dumped.",
    ]
    reply = collect(lines)[0].reply
    board = build_scoreboard(reply.dump, [])
    assert [p["plain_name"] for p in board["players"]] == ["Fast", "Slow"]
    assert board["columns"][0]["lower_is_better"] and board["columns"][0]["primary"]


def test_a_name_with_colons_is_kept_whole() -> None:
    player = parse_player_line("2,0,1:80:-1:a:b:c:12")
    assert player is not None
    assert (player.play_time, player.team, player.name) == (80, None, "a:b:c:12")
    assert parse_player_line("2,0:80:spectator:^1x:y") is not None


def test_a_player_line_that_cannot_be_read_is_skipped() -> None:
    assert parse_player_line("2,0:80:-1") is None  # no name
    assert parse_player_line("2,x:80:-1:Bob") is None  # not numbers
    assert parse_player_line("2,0:late:-1:Bob") is None
    assert parse_player_line("2,0:80:red:Bob") is None
    assert parse_team_line("1,0:five") is None
    assert parse_team_line(":3") is None  # an empty team slot has no values
    lines = [
        "^7:status:dm_x:1",
        "^7:labels:player:score!!,kills",
        "^7:player:see-labels:garbage",
        "^7:player:see-labels:4,1:10:-1:Ok",
        "^7:end",
        "^7stats dumped.",
    ]
    collector, left = collect(lines)
    assert left == []  # the unreadable line is the poll's, so it is withheld
    board = build_scoreboard(collector.reply.dump, [])
    assert [p["plain_name"] for p in board["players"]] == ["Ok"]


def test_same_named_players_are_paired_with_rows_in_order() -> None:
    from xonotic_webui.events import StatusRow

    lines = [
        "^7:status:dm_x:1",
        "^7:labels:player:score!!",
        "^7:player:see-labels:1:10:-1:Twin",
        "^7:player:see-labels:2:10:-1:Twin",
        "^7:end",
        "^7stats dumped.",
    ]
    reply = collect(lines)[0].reply
    rows = [StatusRow(7, False, "Twin", ping=30), StatusRow(4, True, "Twin", ping=0)]
    board = build_scoreboard(reply.dump, rows)
    # the first Twin the game lists is paired with the lower ent
    assert [(p["values"]["score"], p["ent"], p["bot"]) for p in board["players"]] == [
        (2, 7, False),
        (1, 4, True),
    ]


def test_no_dump_means_no_scoreboard() -> None:
    board = build_scoreboard(None, [])
    assert board["available"] is False
    assert board["players"] == [] and board["columns"] == []


def test_team_colours() -> None:
    assert TEAM_COLORS == {5: "red", 14: "blue", 13: "yellow", 10: "pink"}
    assert [c.key for c in parse_labels(["score!!", "", "elo", "rounds_pl", "caps!"])] == [
        "score",
        "caps",
    ]


# --- 2.3 the clock and the score limit ----------------------------------------------------

BASE = {
    "time": 0.0,
    "game_starttime": 16.0,
    "warmup_stage": 0,
    "warmup_limit": 0,
    "checkrules_overtimesadded": 0,
    "intermission_running": 0,
    "game_stopped": 0,
}


def clock(timelimit: float | None = 10, **values: float) -> dict:
    return compute_clock({**BASE, **values}, timelimit)


def test_playing_with_a_time_limit_counts_down() -> None:
    c = clock(time=16 + 200.4)  # 3 minutes 20 seconds in
    assert (c["phase"], c["left_s"], c["elapsed_s"], c["time_limit_s"]) == (
        "playing",
        400,
        200,
        600,
    )
    assert c["available"] and not c["paused"] and c["overtimes"] == 0


def test_playing_without_a_limit_counts_up() -> None:
    c = clock(timelimit=0, time=16 + 95.9)
    assert (c["phase"], c["left_s"], c["elapsed_s"], c["time_limit_s"]) == (
        "playing",
        None,
        95,
        None,
    )


def test_countdown_before_the_match_start() -> None:
    c = clock(time=7.16676092)
    assert (c["phase"], c["left_s"], c["elapsed_s"]) == ("countdown", 9, None)


def test_warmup_counts_down_its_limit() -> None:
    c = clock(game_starttime=0, warmup_stage=1, warmup_limit=60, time=35.5334015)
    assert (c["phase"], c["left_s"]) == ("warmup", 25)


def test_warmup_without_a_limit_has_no_time_left() -> None:
    c = clock(game_starttime=0, warmup_stage=1, warmup_limit=0, time=35)
    assert (c["phase"], c["left_s"]) == ("warmup", None)


def test_overtime_follows_the_raised_limit() -> None:
    # the game raised ``timelimit`` itself when it added the overtime
    c = clock(timelimit=12, time=16 + 650, checkrules_overtimesadded=1)
    assert (c["phase"], c["left_s"], c["overtimes"]) == ("overtime", 70, 1)


def test_a_raised_limit_is_followed_without_overtime() -> None:
    c = clock(timelimit=15.000001, time=16 + 200)
    assert (c["phase"], c["left_s"], c["time_limit_s"]) == ("playing", 700, 900)


def test_match_over_has_no_time_left() -> None:
    c = clock(time=89.6, intermission_running=1, game_stopped=1)
    assert (c["phase"], c["left_s"], c["elapsed_s"]) == ("ended", None, None)
    assert clock(time=89.6, game_stopped=1)["phase"] == "ended"


def test_time_left_is_floored_at_zero() -> None:
    c = clock(timelimit=1, time=16 + 75)
    assert (c["phase"], c["left_s"]) == ("playing", 0)


def test_the_clock_is_unavailable_without_the_server_time() -> None:
    assert compute_clock({}, 10)["available"] is False
    assert compute_clock({"time": 5.0}, 10)["available"] is False
    assert compute_clock({"game_starttime": 16.0}, 10)["available"] is False


def test_paused_is_carried_into_the_clock() -> None:
    assert compute_clock({**BASE, "time": 6.0}, 10, paused=True)["paused"] is True


def test_the_real_clock_cases_give_the_expected_phases() -> None:
    """Each block of ``match_clock_cases.txt`` is a reply to the clock part of the poll."""
    blocks: dict[str, list[str]] = {}
    current: list[str] = []
    for line in fixture_lines("match_clock_cases.txt"):
        if line.startswith("# ====="):
            current = blocks.setdefault(line.strip("# ="), [])
        elif not line.startswith("#"):
            current.append(line)
    assert len(blocks) >= 8
    phases: dict[str, str] = {}
    for title, lines in blocks.items():
        if not lines:
            continue
        collector, _ = collect(lines)
        r = collector.reply
        phases[title] = compute_clock(r.globals, r.timelimit)["phase"]

    def phase_of(prefix: str) -> str:
        (title,) = [t for t in phases if t.startswith(prefix)]
        return phases[title]

    assert phase_of("warmup: 4s after") == "warmup"
    assert phase_of("warmup: 52s after") == "warmup"
    assert phase_of("warmup limit passed") == "playing"
    assert phase_of("countdown: about 2s") == "countdown"
    assert phase_of("countdown: about 9s") == "countdown"
    assert phase_of("playing: about 26s") == "playing"
    assert phase_of("after sv_cmd extendmatchtime") == "playing"
    assert phase_of("intermission:") == "ended"
    # the autopaused readings are a countdown frozen at the same time
    assert {phase_of("autopaused: empty server")} == {"countdown"}


def test_score_limit_unit_comes_from_the_gametype() -> None:
    assert compute_score_limit(30, "dm") == {"value": 30, "unit": "frags"}
    assert compute_score_limit(10, "ctf") == {"value": 10, "unit": "captures"}
    assert compute_score_limit(50, "tdm") == {"value": 50, "unit": "points"}


def test_no_score_limit_and_unknown_gametype() -> None:
    assert compute_score_limit(0, "dm") == {"value": None, "unit": "frags"}
    assert compute_score_limit(None, "dm") == {"value": None, "unit": "frags"}
    assert compute_score_limit(20, None) == {"value": 20, "unit": "points"}
    assert compute_score_limit(20, "zzz") == {"value": 20, "unit": "points"}
