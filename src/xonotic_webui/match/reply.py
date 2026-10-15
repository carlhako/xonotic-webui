"""The reply to one match-state poll, and the collector that recognises it.

Each tick sends one console line (see :data:`POLL_COMMAND`); the server answers in the
order the commands were given, so the reply is a fixed sequence that ends with a line the
last command prints itself::

    time: 86.5000153                                   <- prvm_global server <name>
    ...
    "timelimit" is "10" ["0"]                          <- cvar reads
    host: ... players: 3 active (16 max) ...           <- status 1 (ping, bots)
    :status:dm_trident:87                              <- sv_cmd printstats
    :labels:player:score!!,...,kills,deaths<,...
    :player:see-labels:<values>:<playtime>:<team>:<name>
    :teamscores:see-labels:<values>:<team>             (team games)
    :end
    stats dumped.                                      <- printed by the command itself

Formats were captured from a 0.8.6 dedicated server (``tests/fixtures/xonotic/match_*``).
Three facts the capture settled:

* a bot has a ``:player:`` line only while ``sv_logscores_bots`` is 1, so the poll sets it
  for the length of the dump (and the watcher puts the operator's value back);
* the live ``:player:`` line has no ent: it is ``<values>:<playtime>:<team>:<name>``,
  where ``<team>`` is a number or the word ``spectator``;
* an unknown global is answered ``No global '<name>' in server!``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from xonotic_webui.colors import strip_colors, strip_leading_codes
from xonotic_webui.events import StatusReplyCollector, StatusRow

GLOBALS: tuple[str, ...] = (
    "time",
    "game_starttime",
    "warmup_stage",
    "warmup_limit",
    "checkrules_overtimesadded",
    "intermission_running",
    "game_stopped",
)

_GLOBAL_LINE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*):\s+(?P<value>\S+)\s*$")
_NO_GLOBAL = re.compile(r"^No global '(?P<name>[^']*)' in server!\s*$")
_CVAR_LINE = re.compile(r'^"(?P<name>timelimit|fraglimit)" is "(?P<value>[^"]*)"')
_LOGSCORES_BOTS = re.compile(r'^"sv_logscores_bots" is "(?P<value>[^"]*)"')
_STATS_DUMPED = "stats dumped."

LOGSCORES_BOTS_QUERY = "sv_logscores_bots"


def poll_command(logscores_bots: str = "0") -> str:
    """The one console line a tick sends (design D1).

    ``sv_logscores_bots`` is raised only around the dump so bots are listed in it, and
    returned to ``logscores_bots``, the value the operator had.
    """
    parts = ["sv_logscores_bots 1"]
    parts += [f"prvm_global server {name}" for name in GLOBALS]
    parts += ["timelimit", "fraglimit", "status 1", "sv_cmd printstats"]
    parts.append(f"sv_logscores_bots {logscores_bots}")
    return "; ".join(parts)


def parse_logscores_bots(plain: str) -> str | None:
    """The value in a ``"sv_logscores_bots" is "<v>" ["<d>"]`` reply line."""
    m = _LOGSCORES_BOTS.match(plain)
    return m.group("value") if m else None


@dataclass(frozen=True)
class RawPlayer:
    values: tuple[float, ...]
    play_time: int
    team: int | None  # None for no team (-1) and for a spectator
    spectator: bool
    name: str  # raw, colour codes intact


@dataclass(frozen=True)
class RawTeam:
    team: int
    values: tuple[float, ...]


@dataclass
class RawDump:
    """The ``:status:`` ... ``:end`` block, as the lines gave it."""

    gametype: str | None = None
    map: str | None = None
    time: int | None = None
    player_labels: list[str] | None = None
    team_labels: list[str] | None = None
    players: list[RawPlayer] = field(default_factory=list)
    teams: list[RawTeam] = field(default_factory=list)


def _numbers(csv: str) -> tuple[float, ...] | None:
    if csv == "":
        return ()
    try:
        return tuple(float(v) for v in csv.split(","))
    except ValueError:
        return None


def parse_player_line(rest: str) -> RawPlayer | None:
    """``<values>:<playtime>:<team>:<name>``, the name last because it may contain ``:``."""
    parts = rest.split(":", 3)
    if len(parts) != 4:
        return None
    csv, play_time, team, name = parts
    values = _numbers(csv)
    if values is None or not play_time.lstrip("-").isdigit():
        return None
    spectator = team == "spectator"
    team_number: int | None = None
    if not spectator:
        if not team.lstrip("-").isdigit():
            return None
        team_number = int(team) if int(team) >= 0 else None
    return RawPlayer(values, int(play_time), team_number, spectator, name)


def parse_team_line(rest: str) -> RawTeam | None:
    """``<values>:<team>``; a team nobody is on is printed with no values."""
    csv, sep, team = rest.rpartition(":")
    if not sep or not team.isdigit():
        return None
    values = _numbers(csv)
    if values is None or not values:
        return None
    return RawTeam(int(team), values)


@dataclass
class MatchReply:
    globals: dict[str, float] = field(default_factory=dict)
    unknown_globals: set[str] = field(default_factory=set)
    timelimit: float | None = None
    fraglimit: float | None = None
    status_rows: list[StatusRow] = field(default_factory=list)
    dump: RawDump | None = None


class MatchReplyCollector:
    """Consumes one poll's reply (``Console.query`` collector).

    Every line it consumes belongs to the poll and is withheld from the console. A line
    it cannot place is left alone, so nothing else is swallowed. It finishes on
    ``stats dumped.``, which the dump command prints even when the event log prints
    nothing.
    """

    def __init__(self) -> None:
        self.reply = MatchReply()
        self._status = StatusReplyCollector()
        self._in_dump = False
        self._done = False

    @property
    def done(self) -> bool:
        return self._done

    def feed(self, raw_line: str) -> bool:
        if self._done:
            return False
        line = strip_leading_codes(raw_line).rstrip("\r")
        plain = strip_colors(raw_line).strip("\r")

        if self._in_dump:
            return self._feed_dump(line)
        if line.startswith(":status:"):
            self._start_dump(line)
            return True
        if plain.strip() == _STATS_DUMPED:
            self._finish()
            return True
        if self._status.feed(raw_line):
            if self._status.done:
                self.reply.status_rows = list(self._status.rows)
            return True
        if (m := _CVAR_LINE.match(plain)) is not None:
            value = _to_float(m.group("value"))
            if m.group("name") == "timelimit":
                self.reply.timelimit = value
            else:
                self.reply.fraglimit = value
            return True
        if (m := _NO_GLOBAL.match(plain)) is not None:
            self.reply.unknown_globals.add(m.group("name"))
            return True
        if (m := _GLOBAL_LINE.match(plain)) is not None and m.group("name") in GLOBALS:
            value = _to_float(m.group("value"))
            if value is not None:
                self.reply.globals[m.group("name")] = value
            return True
        return False

    def _start_dump(self, line: str) -> None:
        self._in_dump = True
        dump = RawDump()
        target, _, seconds = line[len(":status:") :].rpartition(":")
        gametype, sep, map_name = target.partition("_")
        if sep and gametype and map_name:
            dump.gametype, dump.map = gametype, map_name
        if seconds.isdigit():
            dump.time = int(seconds)
        self.reply.dump = dump

    def _feed_dump(self, line: str) -> bool:
        dump = self.reply.dump
        assert dump is not None
        if line == ":end":
            self._in_dump = False
            return True
        if line.startswith(":labels:player:"):
            dump.player_labels = line[len(":labels:player:") :].split(",")
            return True
        if line.startswith(":labels:teamscores:"):
            dump.team_labels = line[len(":labels:teamscores:") :].split(",")
            return True
        if line.startswith(":player:see-labels:"):
            player = parse_player_line(line[len(":player:see-labels:") :])
            if player is not None:
                dump.players.append(player)
            return True  # a line it cannot read is still the poll's, and is skipped
        if line.startswith(":teamscores:see-labels:"):
            team = parse_team_line(line[len(":teamscores:see-labels:") :])
            if team is not None:
                dump.teams.append(team)
            return True
        return False

    def _finish(self) -> None:
        self._done = True
        if not self.reply.status_rows:
            self.reply.status_rows = list(self._status.rows)


def _to_float(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None
