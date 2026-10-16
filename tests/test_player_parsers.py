"""The ``who`` reply collector and the report parser, against real captures."""

from __future__ import annotations

from pathlib import Path

from xonotic_webui.players.recorder import _reported
from xonotic_webui.players.report import (
    ReportParser,
    StatsReportFilter,
    achievements,
    scoreboard,
    weapon_stats,
)
from xonotic_webui.players.store import ReportedPlayer
from xonotic_webui.players.who import WhoReplyCollector

FIXTURES = Path(__file__).parent / "fixtures" / "xonotic"


def fixture_lines(name: str) -> list[str]:
    return (FIXTURES / name).read_text().splitlines()


def feed_all(parser: ReportParser, lines: list[str]) -> list[str]:
    """The lines the parser did *not* consume."""
    return [line for line in lines if not parser.feed(line)]


# --- who ----------------------------------------------------------------------------------


def test_who_reply_fixture_gives_each_slots_fingerprint() -> None:
    collector = WhoReplyCollector()
    lines = fixture_lines("who_reply.txt")
    assert all(collector.feed(line) for line in lines)
    assert collector.done
    assert collector.rows[1].fingerprint == "pzccpd+7+o3Wal/UYuxcjuqhEyXP0u3nN2ep/DNZDWE="
    assert collector.rows[2].fingerprint is None  # a bot
    assert collector.rows[3].fingerprint is None
    # the nickname holds a ``|`` and is cut at 20 characters; neither shifts the columns
    assert collector.rows[4].fingerprint == "26at9HsAeCtoiIFlbO7RLja2myn5t2v7e3Tu804ctPY="
    assert sorted(collector.rows) == [1, 2, 3, 4]


def test_who_ignores_lines_before_and_after_the_reply() -> None:
    collector = WhoReplyCollector()
    lines = fixture_lines("who_reply.txt")
    before = "^7^1Name^7: hello"
    after = "^7:join:5:5:127.0.0.1:x"
    assert collector.feed(before) is False
    assert [collector.feed(line) for line in lines] == [True] * len(lines)
    assert collector.feed(after) is False


def test_an_unrelated_line_inside_the_reply_is_not_consumed() -> None:
    collector = WhoReplyCollector()
    lines = fixture_lines("who_reply.txt")
    chat = "^7^1Name^7: hello"
    assert collector.feed(lines[0]) is True
    assert collector.feed(chat) is False
    for line in lines[1:]:
        assert collector.feed(line) is True
    assert collector.done


def test_an_empty_fingerprint_means_none() -> None:
    collector = WhoReplyCollector()
    for line in [
        "^7List of client information:",
        "^7|^7ent |^7nickname            |^7ping |^7pl |^7time     |^7ip              "
        "|^7crypto_id|^7",
        "^7|^7#1  |^7Nobody              |^720   |^70  |^700:00:03 |^7127.0.0.1       |^7|^7",
        "^7|^7#2  |^7Hidden              |^720   |^70  |^700:00:03 |^7127.0.0.1       |^7hidden|^7",
        "^7Finished listing 2 client(s) out of 16 slots.",
    ]:
        collector.feed(line)
    assert collector.done
    assert collector.rows[1].fingerprint is None
    assert collector.rows[2].fingerprint is None


def test_who_never_keeps_the_address() -> None:
    collector = WhoReplyCollector()
    for line in fixture_lines("who_reply.txt"):
        collector.feed(line)
    assert not any("127.0.0.1" in repr(row) for row in collector.rows.values())


# --- report -------------------------------------------------------------------------------


def test_a_finished_match_report() -> None:
    parser = ReportParser()
    lines = fixture_lines("report_finished.txt")
    leftover = feed_all(parser, lines)
    report = parser.report
    assert report is not None
    assert report.gametype == "dm" and report.map == "atelier"
    assert report.match_id == "0.1791950428.917818"
    assert report.hostname == "Xonotic 0.8.6 Server"
    assert report.duration > 100
    assert report.finished
    # the surrounding match-end lines are not part of the report
    assert any(line.startswith("^7:scores:") for line in leftover)
    assert leftover[-1] == "^7:gameover"
    assert not any(line.startswith(("^7V ", "^7P ", "^7e ")) for line in leftover)

    human, *bots = report.players
    assert human.fingerprint is not None and human.id == 1 and human.name == "^1Spike^7Tester"
    assert human.ranked is True
    assert [b.is_bot for b in bots] == [True, True]
    assert all(b.fingerprint is None for b in bots)
    assert human.events["alivetime"] > 0
    assert human.events["matches"] == 1
    assert weapon_stats(human.events)["shotgun"]["cnt-fired"] == 22
    winners = [p for p in report.players if p.events.get("wins")]
    assert len(winners) == 1 and winners[0].is_bot
    assert achievements(winners[0].events) == {"firstblood": 1}
    assert scoreboard(human.events)["score"] == -1


def test_a_cut_short_match_report_is_not_finished() -> None:
    parser = ReportParser()
    leftover = feed_all(parser, fixture_lines("report_unfinished.txt"))
    report = parser.report
    assert report is not None
    assert not report.finished
    assert not any("wins" in p.events for p in report.players)
    # the next map's start follows the block's blank line and is passed through
    assert [line.split(":")[1] for line in leftover if line.startswith("^7:")] == [
        "gamestart",
        "gameinfo",
        "gameinfo",
    ]


def test_a_player_who_allows_neither_tracking_nor_names() -> None:
    parser = ReportParser()
    feed_all(parser, fixture_lines("report_privacy_optout.txt"))
    report = parser.report
    assert report is not None
    human = report.players[0]
    assert human.key == "player#1"
    assert human.fingerprint is None and human.name is None and human.id == 1
    assert human.events["alivetime"] > 0


def test_team_lines_and_team_ids_are_understood() -> None:
    parser = ReportParser()
    lines = [
        "^7V 9",
        "^7G tdm",
        "^7M atelier",
        "^7I 0.1.1",
        "^7D 60.5",
        "^7Q team#14",
        "^7e total-score 3",
        "^7Q team#5",
        "^7P bot#8#Airhead",
        "^7i 8",
        "^7n [BOT]Airhead",
        "^7t 5",
        "^7e total-score 2",
        "^7",
    ]
    assert feed_all(parser, lines) == []
    report = parser.report
    assert report is not None
    assert report.team_ids == [14, 5]
    assert report.players[0].team == 5
    assert report.players[0].events == {"total-score": 2.0}
    # the team's own ``e`` lines are kept apart from the players'; a team with none is empty
    assert report.teams == {14: {"score": 3.0}, 5: {}}


def test_a_team_deathmatch_report_gives_each_teams_score() -> None:
    parser = ReportParser()
    leftover = feed_all(parser, fixture_lines("report_tdm_finished.txt"))
    report = parser.report
    assert report is not None and report.finished
    assert report.gametype == "tdm"
    assert report.team_ids == [14, 5]
    # red (5) scored nothing, so the game wrote no line for it
    assert report.teams == {14: {"score": 3.0}, 5: {}}
    assert {p.team for p in report.players} == {5, 14}
    assert not any(line.startswith("^7e ") for line in leftover)
    winners = {p.team for p in report.players if p.events.get("wins")}
    assert winners == {14}


def test_a_ctf_report_gives_team_captures_and_scores() -> None:
    parser = ReportParser()
    feed_all(parser, fixture_lines("report_ctf_finished.txt"))
    report = parser.report
    assert report is not None
    assert report.teams == {14: {"caps": 1.0, "score": 45.0}, 5: {"caps": 1.0, "score": 74.0}}
    # a drawn match: nobody has ``wins``
    assert not any(p.events.get("wins") for p in report.players)
    assert scoreboard(report.players[0].events).get("caps", 0.0) == 0.0
    labels = set().union(*(scoreboard(p.events) for p in report.players))
    assert {"caps", "fckills", "returns", "drops", "pickups", "captime"} <= labels


def test_a_deathmatch_report_has_no_teams() -> None:
    parser = ReportParser()
    feed_all(parser, fixture_lines("report_finished.txt"))
    assert parser.report is not None
    assert parser.report.teams == {}
    assert all(p.team is None for p in parser.report.players)


def test_a_player_who_left_has_figures_but_is_not_on_the_final_board() -> None:
    parser = ReportParser()
    feed_all(parser, fixture_lines("report_leaver.txt"))
    report = parser.report
    assert report is not None and report.finished
    by_name = {p.name: p for p in report.players}
    leaver = by_name["^1Leav^7er"]
    assert leaver.events["alivetime"] > 0 and leaver.events["joins"] == 1
    assert not any(
        leaver.events.get(e) for e in ("scoreboardvalid", "scoreboardpos", "rank", "matches")
    )
    for name in ("^2Stay^7er", "^4Late^7Joiner"):
        assert by_name[name].events["scoreboardvalid"] == 1
        assert by_name[name].events["matches"] == 1


def test_a_player_spectating_at_the_end_is_not_on_the_final_board() -> None:
    parser = ReportParser()
    feed_all(parser, fixture_lines("report_spectator_at_end.txt"))
    report = parser.report
    assert report is not None and report.finished
    by_name = {p.name: p for p in report.players}
    watcher = by_name["^5Watch^7er"]
    assert watcher.events["alivetime"] > 0
    assert "rank" in watcher.events  # rank alone does not mean they were on the board
    assert not any(watcher.events.get(e) for e in ("scoreboardvalid", "scoreboardpos", "matches"))
    assert by_name["^2Stay^7er"].events["scoreboardvalid"] == 1


def test_a_block_interrupted_by_an_unrelated_line_passes_it_through() -> None:
    parser = ReportParser()
    lines = fixture_lines("report_finished.txt")
    start = lines.index("^7V 9")
    cut = start + 14
    chat = "^7^1Name^7: still here"
    leftover = feed_all(parser, [*lines[:cut], chat, *lines[cut:]])
    assert chat in leftover
    assert parser.report is None  # the broken block is dropped, not half-applied
    # lines of the broken remainder are not mistaken for a report either
    assert not parser.in_block


def test_a_stray_V_line_followed_by_normal_output() -> None:
    parser = ReportParser()
    assert parser.feed("^7V 9") is True
    assert parser.feed("^7^1Name^7: hello") is False
    assert parser.feed("^7:join:1:1:127.0.0.1:x") is False
    assert parser.report is None
    assert not parser.in_block


def test_a_report_without_names_still_parses() -> None:
    parser = ReportParser()
    lines = ["^7V 9", "^7P player#4", "^7i 4", "^7e alivetime 12", "^7"]
    assert feed_all(parser, lines) == []
    assert parser.report is not None
    assert parser.report.players[0].name is None


def test_lines_that_only_look_like_reports_are_left_alone() -> None:
    parser = ReportParser()
    for line in ["^7e matches 1", "^7P something", "^7Q team#1", "^7i 3", "^7"]:
        assert parser.feed(line) is False
    assert parser.report is None


def test_a_second_block_replaces_the_first() -> None:
    parser = ReportParser()
    first = ["^7V 9", "^7M one", "^7"]
    second = ["^7V 9", "^7M two", "^7"]
    feed_all(parser, first)
    assert parser.report is not None and parser.report.map == "one"
    feed_all(parser, second)
    assert parser.report.map == "two"


def test_the_console_filter_consumes_exactly_the_block() -> None:
    filt = StatsReportFilter()
    lines = fixture_lines("report_finished.txt")
    kept = [line for line in lines if not filt.feed(line)]
    assert all(not line.startswith(("^7V ", "^7P ", "^7e ", "^7i ", "^7n ")) for line in kept)
    assert kept[0].startswith("^7:scores:") and kept[-1] == "^7:gameover"
    assert "^7:end" in kept


# --- what a report says about each player (match-history D8) --------------------------------


def reported_by_name(fixture: str) -> dict[str | None, ReportedPlayer]:
    parser = ReportParser()
    feed_all(parser, fixture_lines(fixture))
    assert parser.report is not None
    return {p.name: _reported(p) for p in parser.report.players}


def test_a_ctf_players_captures_are_kept_without_knowing_ctf() -> None:
    parser = ReportParser()
    feed_all(parser, fixture_lines("report_ctf_finished.txt"))
    assert parser.report is not None
    capper = next(p for p in parser.report.players if p.name == "[BOT]Lion")
    r = _reported(capper)
    assert r.scores is not None
    assert r.scores["caps"] == 1 and r.scores["captime"] == 2543
    assert r.scores["score"] == 23 and r.scores["kills"] == 2 and r.scores["pickups"] == 1
    assert r.team == 5 and r.board_pos == 2
    # the hidden labels are never kept, and the counters stay as they were
    assert "elo" not in r.scores and "rounds_pl" not in r.scores
    assert r.extra is not None and r.extra["caps"] == 1


def test_a_team_games_players_have_their_team_and_board_position() -> None:
    got = reported_by_name("report_tdm_finished.txt")
    assert got["[BOT]Scorcher"].team == 14 and got["[BOT]Scorcher"].board_pos == 1
    assert got["^3Team^7Tester"].team == 5 and got["^3Team^7Tester"].board_pos == 4
    assert got["^3Team^7Tester"].name == "^3Team^7Tester"


def test_a_deathmatch_player_has_no_team() -> None:
    got = reported_by_name("report_finished.txt")
    assert all(r.team is None for r in got.values())
    assert [r.board_pos for r in got.values()] == [3, 1, 2]


def test_a_leaver_has_no_board_position_and_is_not_valid() -> None:
    leaver = reported_by_name("report_leaver.txt")["^1Leav^7er"]
    assert leaver.board_pos is None
    assert leaver.scoreboard_valid is False
    assert leaver.alivetime > 0 and leaver.avglatency > 0
    assert leaver.name == "^1Leav^7er"


def test_a_spectator_at_the_end_is_not_valid_and_has_no_position() -> None:
    watcher = reported_by_name("report_spectator_at_end.txt")["^5Watch^7er"]
    assert watcher.board_pos is None and watcher.scoreboard_valid is False
    assert watcher.rank is not None  # rank is written, but does not put them on the board


def test_a_player_with_no_report_name_has_none_unless_a_fallback_is_given() -> None:
    parser = ReportParser()
    feed_all(parser, fixture_lines("report_privacy_optout.txt"))
    assert parser.report is not None
    human = parser.report.players[0]
    assert _reported(human).name is None
    assert _reported(human, "^2Seen^7Name").name == "^2Seen^7Name"
    # the report's own name wins over the fallback
    parser = ReportParser()
    feed_all(parser, fixture_lines("report_finished.txt"))
    assert parser.report is not None
    assert _reported(parser.report.players[0], "other").name == "^1Spike^7Tester"
