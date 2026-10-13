"""The status snapshot served to clients (server-status spec)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from xonotic_webui.colors import strip_colors


@dataclass
class Player:
    ent: int  # the server's slot number; unique among connected clients
    name: str  # raw, colour codes intact
    bot: bool
    id: int | None = None  # the event log's player id, when a join was observed

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ent": self.ent,
            "name": self.name,
            "plain_name": strip_colors(self.name),
            "bot": self.bot,
        }


@dataclass(frozen=True)
class StatusSnapshot:
    state: str
    map: str | None = None
    gametype: str | None = None
    players: tuple[Player, ...] = ()
    # "enabled" once confirmed, "unavailable" when the event log cannot be relied on,
    # None while unknown or the server is not running.
    event_log: str | None = None
    last_crash: dict[str, Any] | None = None
    restart_abandoned: bool = False
    last_start_failure: dict[str, Any] | None = None
    # The latest match action (go to map, skip, restart) and how it is going.
    action: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def human_count(self) -> int:
        return sum(1 for p in self.players if not p.bot)

    @property
    def bot_count(self) -> int:
        return sum(1 for p in self.players if p.bot)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "map": self.map,
            "gametype": self.gametype,
            "players": [p.to_dict() for p in self.players],
            "human_count": self.human_count,
            "bot_count": self.bot_count,
            "event_log": self.event_log,
            "last_crash": self.last_crash,
            "restart_abandoned": self.restart_abandoned,
            "last_start_failure": self.last_start_failure,
            "action": self.action,
        }
