"""The scoreboard from the game's own ``:labels:`` and ``:player:`` lines (design D5).

Nothing here knows a gametype: the columns, their order, the sort columns and which way
they sort all come from the label list, so a gametype with its own columns needs no change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from xonotic_webui.colors import strip_colors
from xonotic_webui.events import StatusRow
from xonotic_webui.match.reply import RawDump, RawPlayer

# The game itself does not show these.
HIDDEN_COLUMNS = frozenset({"elo", "rounds_pl"})

# Colours for the team numbers the game uses. -1 (no team) has none.
TEAM_COLORS: dict[int, str] = {5: "red", 14: "blue", 13: "yellow", 10: "pink"}

_LABEL = re.compile(r"^(?P<key>[^!<]*)(?P<marks>[!<]*)$")

# Display names for the columns the game is known to report. A column not listed here is
# shown under its own key.
LABELS: dict[str, str] = {
    "score": "Score",
    "kills": "Kills",
    "deaths": "Deaths",
    "suicides": "Suicides",
    "teamkills": "Team kills",
    "dmg": "Damage",
    "dmgtaken": "Damage taken",
    "caps": "Captures",
    "fckills": "FC kills",
    "returns": "Returns",
    "drops": "Drops",
    "pickups": "Pickups",
    "captime": "Capture time",
}


@dataclass(frozen=True)
class Column:
    index: int  # position in the value list
    key: str
    primary: bool
    secondary: bool
    lower_is_better: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": LABELS.get(self.key, self.key.replace("_", " ").capitalize()),
            "primary": self.primary,
            "secondary": self.secondary,
            "lower_is_better": self.lower_is_better,
        }


def parse_labels(labels: list[str]) -> list[Column]:
    """The kept columns of a ``:labels:`` list: named, and not one the game hides."""
    columns: list[Column] = []
    for index, label in enumerate(labels):
        m = _LABEL.match(label.strip())
        if m is None or not m.group("key") or m.group("key") in HIDDEN_COLUMNS:
            continue
        marks = m.group("marks")
        columns.append(
            Column(
                index=index,
                key=m.group("key"),
                primary="!!" in marks,
                secondary="!" in marks and "!!" not in marks,
                lower_is_better="<" in marks,
            )
        )
    return columns


def _number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def _values(columns: list[Column], raw: tuple[float, ...]) -> dict[str, int | float]:
    return {c.key: _number(raw[c.index]) if c.index < len(raw) else 0 for c in columns}


def _sort_key(columns: list[Column]):
    primary = next((c for c in columns if c.primary), None)
    secondary = next((c for c in columns if c.secondary), None)

    def key(item: tuple[RawPlayer, dict[str, int | float], str]) -> tuple:
        _player, values, plain = item
        parts: list[float] = []
        for column in (primary, secondary):
            if column is None:
                parts.append(0)
                continue
            value = float(values.get(column.key, 0))
            parts.append(value if column.lower_is_better else -value)
        return (parts[0], parts[1], plain.lower())

    return key


def _join_rows(rows: list[StatusRow]) -> dict[str, list[StatusRow]]:
    by_name: dict[str, list[StatusRow]] = {}
    for row in sorted(rows, key=lambda r: r.ent):
        by_name.setdefault(strip_colors(row.name), []).append(row)
    return by_name


def build_scoreboard(dump: RawDump | None, rows: list[StatusRow]) -> dict[str, Any]:
    """The scoreboard part of a snapshot; ``available`` is false without a player table."""
    if dump is None or dump.player_labels is None:
        return {"available": False, "columns": [], "players": [], "spectators": [], "teams": []}

    columns = parse_labels(dump.player_labels)
    if columns and not any(c.primary for c in columns):
        first = columns[0]
        columns[0] = Column(first.index, first.key, True, False, first.lower_is_better)
    by_name = _join_rows(rows)

    def joined(raw: RawPlayer) -> tuple[StatusRow | None, str]:
        plain = strip_colors(raw.name)
        candidates = by_name.get(plain)
        return (candidates.pop(0) if candidates else None), plain

    playing: list[tuple[RawPlayer, dict[str, int | float], str, StatusRow | None]] = []
    spectators: list[dict[str, Any]] = []
    for raw in dump.players:
        row, plain = joined(raw)
        if raw.spectator:
            spectators.append(
                {
                    "ent": row.ent if row else None,
                    "name": raw.name,
                    "plain_name": plain,
                    "bot": bool(row and row.bot),
                }
            )
        else:
            playing.append((raw, _values(columns, raw.values), plain, row))

    order = _sort_key(columns)
    playing.sort(key=lambda item: order(item[:3]))
    players = [
        {
            "ent": row.ent if row else None,
            "name": raw.name,
            "plain_name": plain,
            "bot": bool(row and row.bot),
            "ping": row.ping if row else None,
            "time_s": raw.play_time,
            "team": raw.team,
            "values": values,
        }
        for raw, values, plain, row in playing
    ]

    teams: list[dict[str, Any]] = []
    if dump.team_labels is not None and dump.teams:
        team_columns = parse_labels(dump.team_labels)
        team_order = next((c for c in team_columns if c.primary), None)
        built = [
            {
                "team": t.team,
                "color": TEAM_COLORS.get(t.team),
                "values": _values(team_columns, t.values),
            }
            for t in dump.teams
        ]
        if team_order is not None:
            built.sort(key=lambda t: -float(t["values"].get(team_order.key, 0)))
        teams = built

    return {
        "available": True,
        "columns": [c.to_dict() for c in columns],
        "players": players,
        "spectators": spectators,
        "teams": teams,
    }
