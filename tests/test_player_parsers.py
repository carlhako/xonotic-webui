"""The ``who`` reply collector and the report parser, against real captures."""

from __future__ import annotations

from pathlib import Path

from xonotic_webui.players.report import (
    ReportParser,
    StatsReportFilter,
    achievements,
    scoreboard,
    weapon_stats,
)
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
