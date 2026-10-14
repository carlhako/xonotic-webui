"""Player routes: the recorded history as a sortable list and a per-player detail."""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Query, Request, Response

from xonotic_webui.api._shared import api_error
from xonotic_webui.api.schemas import (
    ErrorResponse,
    PlayerAchievement,
    PlayerAlias,
    PlayerDetail,
    PlayerExtra,
    PlayerList,
    PlayerRow,
    PlayerWeapon,
)
from xonotic_webui.colors import strip_colors
from xonotic_webui.players.store import SORT_COLUMNS, PlayerStoreError

if TYPE_CHECKING:
    from xonotic_webui.runtime import Runtime

SortColumn = Literal[
    "name",
    "frags",
    "deaths",
    "kd",
    "score",
    "wins",
    "matches",
    "time_playing",
    "time_on_server",
    "accuracy",
    "last_seen",
]
assert set(SortColumn.__args__) == set(SORT_COLUMNS)  # type: ignore[attr-defined]

MAX_LIMIT = 200
DEFAULT_LIMIT = 50
KEY_PREFIX_LENGTH = 8

_UNAVAILABLE = {
    503: {"model": ErrorResponse, "description": "Player history is not being recorded."},
}


def _row(data: dict) -> dict:
    return {
        "id": data["id"],
        "name": data["name"],
        "plain_name": strip_colors(data["name"]),
        "is_bot": data["is_bot"],
        "frags": data["frags"],
        "deaths": data["deaths"],
        "kd": data["kd"],
        "suicides": data["suicides"],
        "teamkills": data["teamkills"],
        "score": data["score"],
        "wins": data["wins"],
        "matches": data["matches"],
        "time_playing": data["time_playing"],
        "time_on_server": data["time_on_server"],
        "accuracy": data["accuracy"],
        "first_seen": data["first_seen"],
        "last_seen": data["last_seen"],
    }


def _accuracy(hit: float, fired: float) -> float | None:
    return hit / fired if fired > 0 else None


def _key_prefix(key: str) -> str | None:
    """The start of a key fingerprint; name and bot identities have none."""
    if not key.startswith("fp:"):
        return None
    return key[3 : 3 + KEY_PREFIX_LENGTH]


def build_players_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(tags=["players"])
    store = runtime.players_store

    def available() -> None:
        if not runtime.recorder.enabled:
            raise api_error(503, "players_unavailable", "player history is not being recorded")

    @router.get(
        "/players",
        response_model=PlayerList,
        responses={304: {"description": "Unchanged since If-None-Match."}, **_UNAVAILABLE},
        summary="Recorded players with their totals, sorted, filtered and paged",
    )
    async def list_players(
        request: Request,
        response: Response,
        sort: SortColumn = "frags",
        order: Literal["asc", "desc"] = "desc",
        q: str | None = Query(default=None, max_length=100, description="Name search."),
        bots: bool = False,
        limit: int = Query(default=DEFAULT_LIMIT, ge=1, description="At most 200 are returned."),
        offset: int = Query(default=0, ge=0),
    ) -> PlayerList | Response:
        available()
        limit = min(limit, MAX_LIMIT)
        query_hash = hashlib.sha1(
            f"{sort}|{order}|{q or ''}|{bots}|{limit}|{offset}".encode(), usedforsecurity=False
        ).hexdigest()[:12]
        etag = f'"{store.revision}-{query_hash}"'
        match = request.headers.get("if-none-match", "")
        if etag in {tag.strip() for tag in match.split(",")}:
            return Response(status_code=304, headers={"ETag": etag})
        try:
            total, rows = await store.list_players(
                sort=sort,
                descending=order == "desc",
                query=q.strip() if q else None,
                bots=bots,
                limit=limit,
                offset=offset,
                now=int(time.time()),
            )
        except PlayerStoreError as exc:
            raise api_error(503, "players_unavailable", str(exc)) from exc
        response.headers["ETag"] = etag
        return PlayerList(
            revision=store.revision,
            total=total,
            players=[PlayerRow(**_row(r)) for r in rows],
        )

    @router.get(
        "/players/{player_id}",
        response_model=PlayerDetail,
        responses={
            404: {"model": ErrorResponse, "description": "No such player."},
            **_UNAVAILABLE,
        },
        summary="Everything recorded for one player",
    )
    async def get_player(player_id: int) -> PlayerDetail:
        available()
        try:
            data = await store.get_player(player_id, now=int(time.time()))
        except PlayerStoreError as exc:
            raise api_error(503, "players_unavailable", str(exc)) from exc
        if data is None:
            raise api_error(404, "player_not_found", f"no player {player_id}")
        return PlayerDetail(
            **_row(data),
            aliases=[
                PlayerAlias(
                    name=a["name"], plain_name=strip_colors(a["name"]), last_used=a["last_used"]
                )
                for a in data["aliases"]
            ],
            sessions=data["sessions"],
            key_prefix=_key_prefix(data["key"]),
            damage_dealt=data["dmg"],
            damage_taken=data["dmgtaken"],
            avg_latency=data["avg_latency"],
            weapons=[
                PlayerWeapon(**w, accuracy=_accuracy(w["hit"], w["fired"])) for w in data["weapons"]
            ],
            achievements=[PlayerAchievement(**a) for a in data["achievements"]],
            extra=[PlayerExtra(**e) for e in data["extra"]],
            has_match_stats=data["has_match_stats"],
        )

    return router
