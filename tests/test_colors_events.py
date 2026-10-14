"""Colour stripping and event parsing against real captures."""

from __future__ import annotations

from pathlib import Path

import pytest

from xonotic_webui.colors import strip_colors, strip_leading_codes
from xonotic_webui.events import (
    GameStart,
    PlayerJoin,
    PlayerKill,
    PlayerName,
    PlayerPart,
    StatusReplyCollector,
    is_loaded_map,
    is_map_line,
    parse_event,
)

FIXTURES = Path(__file__).parent / "fixtures" / "xonotic"


def fixture_lines(name: str) -> list[str]:
    return (FIXTURES / name).read_text().splitlines()


# --- colour stripping -----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "plain"),
    [
        ("plain", "plain"),
        ("^1Red^7 Name", "Red Name"),
        ("^xf80Orange^7", "Orange"),
        ("^1Red^xf80Orange^7 Pl:ay^^er", "RedOrange Pl:ay^er"),
        ("a^^b", "a^b"),
        ("^^1not-a-colour", "^1not-a-colour"),
        ("^x12 short", "^x12 short"),  # fewer than 3 hex digits is literal
        ("^xGGG", "^xGGG"),
        ("^x1234", "4"),  # three digits consumed, the rest is text
        ("trailing^", "trailing^"),
        ("^", "^"),
        ("", ""),
        ("\x1b[1;31mRed\x1b[m Name", "Red Name"),
    ],
)
def test_strip_colors(raw: str, plain: str) -> None:
    assert strip_colors(raw) == plain


def test_strip_leading_codes_only_touches_the_start() -> None:
    assert strip_leading_codes("^7^7:join:1:1:bot:^1x") == ":join:1:1:bot:^1x"
    assert strip_leading_codes("^7^xf80:part:3") == ":part:3"
    assert strip_leading_codes(":gamestart:dm_a:1") == ":gamestart:dm_a:1"


# --- event parsing: real captures ------------------------------------------


def test_startup_capture_yields_gamestart() -> None:
    events = [e for line in fixture_lines("startup.txt") if (e := parse_event(line))]
    assert len(events) == 1
    start = events[0]
    assert isinstance(start, GameStart)
    assert start.gametype == "dm"
    assert start.map == "atelier"
    assert start.match_id.startswith("0.")


def test_human_session_events() -> None:
    events = [e for line in fixture_lines("session_humans_only.txt") if (e := parse_event(line))]
    assert PlayerJoin(1, 1, False, "^1Red^xf80Orange^7 Pl:ay^^er") in events
    assert PlayerName(1, "^xf0fMagic^7Name") in events
    assert PlayerPart(1) in events


def test_bot_and_ipv6_joins() -> None:
    events = [e for line in fixture_lines("session_humans_bots_v6.txt") if (e := parse_event(line))]
    joins = [e for e in events if isinstance(e, PlayerJoin)]
    assert [(j.player_id, j.ent, j.bot) for j in joins] == [
        (1, 1, False),
        (2, 3, True),
        (3, 2, False),
    ]
    assert joins[1].name == "[BOT]Resurrection"
    # the IPv6 address is delimiter-escaped, so the name is still the last field
    assert joins[2].name == "V6 ^4Blue^7"


def test_match_boundary_events() -> None:
    events = [e for line in fixture_lines("match_end_next_map.txt") if (e := parse_event(line))]
    assert events == [GameStart("dm", "boil", events[0].match_id)]


def test_anticheat_and_other_lines_are_ignored() -> None:
    lines = fixture_lines("session_ansi_translated.txt")
    anticheat = [line for line in lines if ":anticheat:" in line]
    assert anticheat, "the capture should contain anticheat lines"
    assert all(parse_event(line) is None for line in anticheat)


@pytest.mark.parametrize(
    "line",
    [
        "",
        "^7Switching to map atelier",
        "^7:gamestart:nounderscore:1",
        "^7:join:notanumber:1:bot:x",
        "^7:join:1:1:bot",  # no name field
        "^7:part:",
        "^7:team:1:-1:4",
        "^7:scores:dm_atelier:30",
        "^7:gameover",
    ],
)
def test_unrecognised_lines(line: str) -> None:
    assert parse_event(line) is None


def test_map_name_may_contain_underscores() -> None:
    event = parse_event("^7:gamestart:dm_leave_em_behind:0.1.2")
    assert event == GameStart("dm", "leave_em_behind", "0.1.2")


def test_ansi_translated_names_still_parse_structure() -> None:
    # Default (untranslated-off) console: the codes are ANSI SGR, not ``^N``.
    lines = fixture_lines("session_ansi_translated.txt")
    joins = [e for line in lines if isinstance(e := parse_event(line), PlayerJoin)]
    assert joins
    assert strip_colors(joins[0].name) == "RedOrange Pl:ay^er"


# --- status 1 replies --------------------------------------------------------


def collect(name: str) -> StatusReplyCollector:
    c = StatusReplyCollector()
    for line in fixture_lines(name):
        c.feed(line)
    return c


def test_status_empty() -> None:
    c = collect("status1_empty.txt")
    assert c.done
    assert c.map == "xoylent"
    assert c.rows == []


def test_status_one_human_with_colours() -> None:
    c = collect("status1_one_human.txt")
    assert c.done
    assert len(c.rows) == 1
    row = c.rows[0]
    assert (row.ent, row.bot) == (1, False)
    assert row.name == "^xf0fMagic^7Name"


def test_status_humans_bots_ipv6() -> None:
    c = collect("status1_humans_bots_v6.txt")
    assert c.done and c.map == "atelier"
    assert [(r.ent, r.bot, strip_colors(r.name)) for r in c.rows] == [
        (1, False, "Renamed:Pl"),
        (2, False, "V6 Blue"),
        (3, True, "[BOT]Resurrection"),
    ]


def test_status_premap_reports_placeholder() -> None:
    c = StatusReplyCollector()
    for line in fixture_lines("status_premap.txt"):
        c.feed(line)
    assert c.map == "_init/_init"
    assert not is_loaded_map(c.map)


def test_collector_ignores_unrelated_lines_before_and_after() -> None:
    c = StatusReplyCollector()
    assert c.feed("^7:join:1:1:bot:[BOT]x") is False  # before the reply starts
    for line in fixture_lines("status1_one_human.txt"):
        assert c.feed(line) is True
    assert c.done
    assert c.feed("^7:part:1") is False  # after it ended


def test_map_line_helper() -> None:
    assert is_map_line("map:      atelier") == "atelier"
    assert is_map_line("map:      _init/_init") == "_init/_init"
    assert is_map_line("host:     spike") is None


# --- kills (player-stats) ---------------------------------------------------------------


def test_every_captured_kill_shape_parses() -> None:
    lines = fixture_lines("kill_variants.txt")
    events = [parse_event(line) for line in lines]
    assert all(isinstance(e, PlayerKill) for e in events)
    assert {e.mode for e in events if isinstance(e, PlayerKill)} == {
        "frag",
        "tk",
        "suicide",
        "accident",
    }


def test_kill_fields() -> None:
    assert parse_event("^7:kill:frag:3:2:type=258:items=2-1:victimitems=2-1") == PlayerKill(
        "frag", 3, 2
    )
    assert parse_event("^7:kill:tk:4:8:type=522:items=10-1:victimitems=8-1") == PlayerKill(
        "tk", 4, 8
    )
    # a suicide and an accident carry the victim as the killer
    assert parse_event("^7:kill:suicide:1:1:type=KILL:items=2-1T") == PlayerKill("suicide", 1, 1)
    assert parse_event("^7:kill:accident:3:3:type=HURTTRIGGER:items=2-1") == PlayerKill(
        "accident", 3, 3
    )


@pytest.mark.parametrize(
    "line",
    [
        "^7:kill:frag:x:2:type=1",
        "^7:kill:frag:2",
        "^7:kill",
        "^7:kill::1:2",
        "^7:kill:teleport:1:2:type=1",  # a mode this version does not know
    ],
)
def test_malformed_or_unknown_kills_are_ignored(line: str) -> None:
    assert parse_event(line) is None
