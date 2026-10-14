"""Recognition of Xonotic event-log lines and ``status 1`` replies.

All formats here were captured from a live 0.8.6 dedicated server; see
``openspec/changes/bootstrap-xonotic-webui/design.md`` (Spike findings) and
``tests/fixtures/xonotic/``. Anything unrecognised is ``None``: the event log carries many
lines (anticheat, votes, scores) that are normal and not needed.

Event lines start with ``:`` after the leading colour reset::

    :gamestart:<gametype>_<map>:<matchid>
    :join:<playerid>:<ent>:<ip|bot>:<name>
    :name:<playerid>:<name>
    :part:<playerid>
    :kill:<mode>:<killerid>:<victimid>:type=<deathtype>:items=...

The panel launches the server with ``sv_eventlog_ipv6_delimiter 1`` so the address field
never contains a colon, which keeps ``<name>`` (the last field, which may contain colons
and colour codes) unambiguous.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from xonotic_webui.colors import strip_colors, strip_leading_codes


@dataclass(frozen=True)
class GameStart:
    gametype: str
    map: str
    match_id: str


@dataclass(frozen=True)
class PlayerJoin:
    player_id: int
    ent: int
    bot: bool
    name: str  # raw, colour codes intact


@dataclass(frozen=True)
class PlayerName:
    player_id: int
    name: str  # raw, colour codes intact


@dataclass(frozen=True)
class PlayerPart:
    player_id: int


KILL_MODES = frozenset({"frag", "tk", "suicide", "accident"})


@dataclass(frozen=True)
class PlayerKill:
    """A death. ``suicide`` and ``accident`` carry the victim as the killer."""

    mode: str  # one of KILL_MODES
    killer_id: int
    victim_id: int


Event = GameStart | PlayerJoin | PlayerName | PlayerPart | PlayerKill


def parse_event(raw_line: str) -> Event | None:
    """Parse one console line into an event, or ``None`` if it is not one we use."""
    line = strip_leading_codes(raw_line)
    if not line.startswith(":"):
        return None
    kind, _, rest = line[1:].partition(":")
    try:
        if kind == "gamestart":
            target, _, match_id = rest.partition(":")
            gametype, sep, map_name = target.partition("_")
            if not sep or not gametype or not map_name:
                return None
            return GameStart(gametype=gametype, map=map_name, match_id=match_id)
        if kind == "join":
            player_id, ent, ip, name = rest.split(":", 3)
            return PlayerJoin(int(player_id), int(ent), bot=ip == "bot", name=name)
        if kind == "name":
            player_id, name = rest.split(":", 1)
            return PlayerName(int(player_id), name)
        if kind == "part":
            return PlayerPart(int(rest.split(":", 1)[0]))
        if kind == "kill":
            mode, killer, victim = rest.split(":", 3)[:3]
            if mode not in KILL_MODES:
                return None
            return PlayerKill(mode, int(killer), int(victim))
    except ValueError:
        return None
    return None


# ---------------------------------------------------------------------------
# ``status 1`` replies
# ---------------------------------------------------------------------------

PRE_MAP = "_init/_init"

_HOST_RE = re.compile(r"^host:\s")
_MAP_RE = re.compile(r"^map:\s+(?P<map>\S+)\s*$")
_PLAYERS_RE = re.compile(r"^players:\s+(?P<active>\d+) active \((?P<max>\d+) max\)\s*$")
_HEADER_RE = re.compile(r"^IP\s+%pl\s+ping\s+time\s+frags\s+no\s+name\s*$")
_ROW_RE = re.compile(
    r"^(?P<ip>\S+)\s+(?P<pl>-?\d+)\s+(?P<ping>-?\d+)\s+(?P<time>[\d:]+)\s+"
    r"(?P<frags>-?\d+)\s+#(?P<ent>\d+)\s+(?P<name>.*)$"
)
_BOT_ADDRESS = "botclient"


@dataclass(frozen=True)
class StatusRow:
    ent: int
    bot: bool
    name: str  # raw, colour codes intact (a leading ``^7`` reset removed)


def is_map_line(plain: str) -> str | None:
    """The map named by a ``map:`` line of a status reply, or ``None``."""
    m = _MAP_RE.match(plain)
    return m.group("map") if m else None


def is_loaded_map(map_name: str) -> bool:
    return map_name != PRE_MAP


class StatusReplyCollector:
    """Collects one ``status 1`` reply, which has no terminator.

    The reply is ``host:`` ... ``map:`` ... ``players: N active (M max)``, a blank line, a
    column header, then exactly N player rows. Feed it each console line; it reports
    whether the line belonged to the reply so the console can withhold it.
    """

    def __init__(self) -> None:
        self.map: str | None = None
        self.rows: list[StatusRow] = []
        self._started = False
        self._expected: int | None = None
        self._seen_header = False
        self._done = False

    @property
    def done(self) -> bool:
        return self._done

    def feed(self, raw_line: str) -> bool:
        """Return True if ``raw_line`` is part of the reply (and so should be consumed)."""
        if self._done:
            return False
        plain = strip_colors(raw_line).strip("\r")
        if not self._started:
            if _HOST_RE.match(plain):
                self._started = True
                return True
            return False
        if self._expected is None:
            if (m := _MAP_RE.match(plain)) is not None:
                self.map = m.group("map")
            elif (m := _PLAYERS_RE.match(plain)) is not None:
                self._expected = int(m.group("active"))
            return True  # version/protocol/timing/blank lines
        if not self._seen_header:
            if plain.strip() == "":
                return True
            if _HEADER_RE.match(plain):
                self._seen_header = True
                if self._expected == 0:
                    self._done = True
                return True
            return False
        # Rows: matched on the colour-stripped line, the name taken from the raw one.
        m = _ROW_RE.match(plain)
        if m is None:
            return False
        self.rows.append(
            StatusRow(
                ent=int(m.group("ent")),
                bot=m.group("ip") == _BOT_ADDRESS,
                name=_raw_name(raw_line),
            )
        )
        if len(self.rows) >= (self._expected or 0):
            self._done = True
        return True


def _raw_name(raw_line: str) -> str:
    """The name column of a status row with its colour codes, from the raw line.

    The row is ``<ip> <pl> <ping> <time> <frags> #<ent> <name>`` with the name last, so
    everything after the ``#<ent>`` token is the name. The server prepends exactly one
    ``^7`` reset to the name column; only that is dropped, so a name that itself starts
    with a colour keeps it.
    """
    m = re.search(r"#\d+\s+", raw_line)
    name = raw_line[m.end() :] if m else raw_line
    return name[2:] if name.startswith("^7") else name
