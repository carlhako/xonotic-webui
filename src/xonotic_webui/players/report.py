"""The end-of-match statistics report, as the game prints it to the console.

With ``g_playerstats_gamereport_uri -`` the game writes its report to the console, one
contiguous block, at match end and from world shutdown (design D6). Captured from a 0.8.6
dedicated server (``tests/fixtures/xonotic/report_*.txt``)::

    V 9                           start of a block
    R xonotic-v0.8.6              header: R G O M I S C U D L
    G dm
    M atelier
    I 0.1791948418.826593         the match id, as in ``:gamestart:``
    S Xonotic 0.8.6 Server
    D 104.666656                  the match's duration in seconds
    Q team#14                     a team (team games), followed by its ``e`` lines
    P <key | bot#<skill>#<name> | player#<id>>
    i 1                           the match's player id
    n ^1Name                      only if the player allows it; bots always have it
    t 14                          the team
    r 1
    e <event> <number>            non-zero values only
    <blank line>                  end of the block

The recogniser is incremental: it is fed one console line at a time and says whether the
line belonged to a report, so the console can withhold it. A block ends at a blank line.
Any other line ends it too and is *not* consumed, so a malformed block cannot swallow the
console.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from xonotic_webui.colors import strip_colors, strip_leading_codes

_START = re.compile(r"^V \d+$")
_HEADER_LETTERS = frozenset("RGOMISCUDL")
_MAX_BLOCK_LINES = 20000

# Longest first: ``cnt-fired`` must be tried before ``fired``.
WEAPON_FIELDS = ("cnt-hit", "cnt-fired", "hit", "fired", "frags")


@dataclass
class ReportPlayer:
    key: str  # the ``P`` value: a fingerprint, ``bot#<skill>#<name>`` or ``player#<id>``
    id: int | None = None  # ``i``: the match's player id
    name: str | None = None  # ``n``, raw with colour codes
    team: int | None = None  # ``t``
    ranked: bool | None = None  # ``r``
    events: dict[str, float] = field(default_factory=dict)

    @property
    def is_bot(self) -> bool:
        return self.key.startswith("bot#")

    @property
    def fingerprint(self) -> str | None:
        """The fingerprint when the key is one (not a bot or an opted-out ``player#``)."""
        if self.key.startswith(("bot#", "player#")) or not self.key:
            return None
        return self.key


@dataclass
class Report:
    gametype: str = ""
    map: str = ""
    match_id: str = ""
    hostname: str = ""
    duration: float = 0.0
    players: list[ReportPlayer] = field(default_factory=list)
    team_ids: list[int] = field(default_factory=list)

    @property
    def finished(self) -> bool:
        """The ``matches`` event is only written when the match reached its end."""
        return any(p.events.get("matches") for p in self.players)


def weapon_stats(events: dict[str, float]) -> dict[str, dict[str, float]]:
    """``acc-<weapon>-<field>`` events grouped by weapon."""
    out: dict[str, dict[str, float]] = {}
    for name, value in events.items():
        if not name.startswith("acc-"):
            continue
        rest = name[4:]
        for fld in WEAPON_FIELDS:
            if rest.endswith("-" + fld):
                weapon = rest[: -(len(fld) + 1)]
                if weapon:
                    out.setdefault(weapon, {})[fld] = value
                break
    return out


def achievements(events: dict[str, float]) -> dict[str, int]:
    return {
        name[len("achievement-") :]: int(value)
        for name, value in events.items()
        if name.startswith("achievement-") and value
    }


def scoreboard(events: dict[str, float]) -> dict[str, float]:
    """The match's scoreboard values by label (``scoreboard-`` over ``total-``)."""
    out: dict[str, float] = {}
    for name, value in events.items():
        if name.startswith("total-"):
            out.setdefault(name[len("total-") :], value)
    for name, value in events.items():
        if name.startswith("scoreboard-"):
            out[name[len("scoreboard-") :]] = value
    return out


class ReportParser:
    """Recognises report blocks in a stream of console lines.

    ``feed`` returns whether the line was part of a report. After the line that ends a
    block, :attr:`report` holds the parsed result (and is replaced by the next block).
    """

    def __init__(self) -> None:
        self.report: Report | None = None
        self._active = False
        self._lines = 0
        self._current: ReportPlayer | None = None
        self._building: Report | None = None
        self._in_team = False

    @property
    def in_block(self) -> bool:
        return self._active

    def feed(self, raw_line: str) -> bool:
        plain = strip_leading_codes(raw_line).rstrip("\r")
        if not self._active:
            if _START.match(strip_colors(plain)):
                self._begin()
                return True
            return False
        self._lines += 1
        if plain.strip() == "":
            self.report = self._building
            self._reset()
            return True
        if self._lines > _MAX_BLOCK_LINES or not self._apply(plain):
            # Not a report line: the block was malformed. Let the line through, and see
            # whether it starts a new block.
            self._reset()
            return self.feed(raw_line)
        return True

    # -- internals -------------------------------------------------------------------
    def _begin(self) -> None:
        self._active = True
        self._lines = 0
        self._current = None
        self._in_team = False
        self._building = Report()

    def _reset(self) -> None:
        self._active = False
        self._current = None
        self._in_team = False
        self._building = None
        self._lines = 0

    def _apply(self, plain: str) -> bool:
        assert self._building is not None
        letter, _, value = plain.partition(" ")
        if len(letter) != 1:
            return False
        report = self._building
        if letter in _HEADER_LETTERS:
            return self._header(report, letter, value)
        if letter == "Q":
            self._current = None
            self._in_team = True
            _, _, tid = value.partition("#")
            if tid.lstrip("-").isdigit():
                report.team_ids.append(int(tid))
            return True
        if letter == "P":
            self._current = ReportPlayer(key=value.strip())
            self._in_team = False
            report.players.append(self._current)
            return True
        if letter == "e":
            return self._event(value)
        player = self._current
        if player is None:
            return False
        try:
            if letter == "i":
                player.id = int(value)
            elif letter == "n":
                player.name = value
            elif letter == "t":
                player.team = int(value)
            elif letter == "r":
                player.ranked = value.strip() == "1"
            else:
                return False
        except ValueError:
            return False
        return True

    @staticmethod
    def _header(report: Report, letter: str, value: str) -> bool:
        if letter == "G":
            report.gametype = value
        elif letter == "M":
            report.map = value
        elif letter == "I":
            report.match_id = value
        elif letter == "S":
            report.hostname = value
        elif letter == "D":
            try:
                report.duration = float(value)
            except ValueError:
                return False
        # R, O, C, U, L are valid but not used
        return True

    def _event(self, value: str) -> bool:
        name, _, number = value.rpartition(" ")
        if not name:
            return False
        try:
            amount = float(number)
        except ValueError:
            return False
        if self._current is not None:
            self._current.events[name] = amount
        elif not self._in_team:
            return False
        return True


class StatsReportFilter:
    """A console filter that withholds report blocks (server-console spec).

    It only says *consumed or not*; the recorder parses its own copy of the lines, so the
    console never depends on it.
    """

    def __init__(self) -> None:
        self._parser = ReportParser()

    def feed(self, raw_line: str) -> bool:
        return self._parser.feed(raw_line)
