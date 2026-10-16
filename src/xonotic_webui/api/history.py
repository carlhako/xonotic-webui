"""Match history routes: the list of past matches and one match's final scoreboard."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Query, Request, Response

from xonotic_webui.api._shared import api_error
from xonotic_webui.api.schemas import (
    ErrorResponse,
    MatchColumnModel,
    MatchDetail,
    MatchHistoryPlayer,
    MatchHistoryScoreboard,
    MatchList,
    MatchSummary,
    MatchTeamModel,
    MatchWinnerPlayer,
    MatchWinnerTeam,
)
from xonotic_webui.colors import strip_colors
from xonotic_webui.match.board import HIDDEN_COLUMNS, LABELS, TEAM_COLORS
from xonotic_webui.players.store import PlayerStoreError

if TYPE_CHECKING:
    from xonotic_webui.runtime import Runtime

MAX_LIMIT = 200
DEFAULT_LIMIT = 50

# Always shown, in this order, even when everyone has 0.
BASE_COLUMNS = ("score", "kills", "deaths", "suicides")

_UNAVAILABLE = {
    503: {"model": ErrorResponse, "description": "Player history is not being recorded."},
}


def _outcome(row: dict[str, Any], current_match_id: str | None) -> str:
    """finished, cut_short, in_progress or no_report (match-history D5)."""
    if row["finished"] is True:
        return "finished"
    if row["finished"] is False:
        return "cut_short"
    # no report so far: it is being played, or it ended without one (a crash)
    if current_match_id is not None and row["match_id"] == current_match_id:
        return "in_progress"
    return "no_report"


def _winner(data: dict[str, Any] | None) -> MatchWinnerTeam | MatchWinnerPlayer | None:
    if data is None:
        return None
    if data["kind"] == "team":
        return MatchWinnerTeam(team=data["team"], color=TEAM_COLORS.get(data["team"]))
    return MatchWinnerPlayer(
        player_id=data["player_id"],
        name=data["name"],
        plain_name=strip_colors(data["name"]),
        is_bot=data["is_bot"],
        others=data["others"],
    )


def _summary(row: dict[str, Any], current_match_id: str | None) -> dict[str, Any]:
    return {
        "id": row["id"],
        "started_at": row["started_at"],
        "map": row["map"],
        "gametype": row["gametype"],
        "duration": row["duration"],
        "outcome": _outcome(row, current_match_id),
        "humans": row["humans"],
        "bots": row["bots"],
        "vs_bots": row["vs_bots"],
        "winner": _winner(row["winner"]),
    }


def _label(key: str) -> str:
    return LABELS.get(key, key.replace("_", " ").capitalize())


def build_columns(value_sets: list[dict[str, float]]) -> list[MatchColumnModel]:
    """The scoreboard's columns (design D3): score, kills, deaths and suicides, then any other
    value that is not zero for someone: the ones the live board knows in its order, then the
    rest alphabetically. Nothing here knows a gametype."""
    present = {
        key
        for values in value_sets
        for key, value in values.items()
        if value and key not in HIDDEN_COLUMNS
    }
    extra = [k for k in LABELS if k in present and k not in BASE_COLUMNS]
    extra += sorted(k for k in present if k not in LABELS)
    return [
        MatchColumnModel(
            key=key,
            label=_label(key),
            primary=key == "score",
            secondary=False,
            lower_is_better=False,
        )
        for key in (*BASE_COLUMNS, *extra)
    ]


def _number(value: float) -> float:
    return int(value) if float(value).is_integer() else value


def _scoreboard(data: dict[str, Any]) -> MatchHistoryScoreboard:
    columns = build_columns(
        [p["values"] for p in data["players"]] + [t["values"] for t in data["teams"]]
    )
    keys = [c.key for c in columns]
    players = [
        MatchHistoryPlayer(
            player_id=p["player_id"],
            name=p["name"],
            plain_name=strip_colors(p["name"]),
            bot=p["is_bot"],
            team=p["team"],
            ping=p["ping"],
            time_s=p["time_s"],
            at_end=p["at_end"],
            values={k: _number(p["values"].get(k, 0.0)) for k in keys},
        )
        for p in data["players"]
    ]
    # The game writes only non-zero team values, so a team with none scored 0: fill the
    # values some team has (and the score) in, so no team shows as missing data.
    team_keys = {"score"} | {k for t in data["teams"] for k in t["values"]}
    team_keys &= set(keys)
    teams = [
        MatchTeamModel(
            team=t["team"],
            color=TEAM_COLORS.get(t["team"]),
            values={k: _number(t["values"].get(k, 0.0)) for k in keys if k in team_keys},
        )
        for t in data["teams"]
    ]
    return MatchHistoryScoreboard(columns=columns, players=players, teams=teams)


def build_history_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(tags=["matches"])
    store = runtime.players_store

    def available() -> None:
        if not runtime.recorder.enabled:
            raise api_error(503, "players_unavailable", "player history is not being recorded")

    @router.get(
        "/matches",
        response_model=MatchList,
        responses={304: {"description": "Unchanged since If-None-Match."}, **_UNAVAILABLE},
        summary="Past matches with a human in them, newest first",
    )
    async def list_matches(
        request: Request,
        response: Response,
        map: str | None = Query(default=None, max_length=100, description="Only this map."),
        gametype: str | None = Query(
            default=None, max_length=50, description='Only this gametype ("unknown" for none).'
        ),
        player: int | None = Query(
            default=None, ge=1, description="Only matches they took part in."
        ),
        vs_bots: bool = Query(default=True, description="False leaves out vs-bots matches."),
        limit: int = Query(default=DEFAULT_LIMIT, ge=1, description="At most 200 are returned."),
        offset: int = Query(default=0, ge=0),
    ) -> MatchList | Response:
        available()
        limit = min(limit, MAX_LIMIT)
        current = runtime.recorder.current_match_id
        # The current match id is in the tag: a crash turns "in progress" into "no report"
        # without any database write, and the revision would not change.
        query_hash = hashlib.sha1(
            f"{map or ''}|{gametype or ''}|{player}|{vs_bots}|{limit}|{offset}".encode(),
            usedforsecurity=False,
        ).hexdigest()[:12]
        etag = f'"{store.revision}-{current or ""}-{query_hash}"'
        sent = request.headers.get("if-none-match", "")
        if etag in {tag.strip() for tag in sent.split(",")}:
            return Response(status_code=304, headers={"ETag": etag})
        try:
            total, rows = await store.list_matches(
                map_name=map or None,
                gametype=gametype or None,
                player_id=player,
                hide_vs_bots=not vs_bots,
                limit=limit,
                offset=offset,
            )
        except PlayerStoreError as exc:
            raise api_error(503, "players_unavailable", str(exc)) from exc
        response.headers["ETag"] = etag
        return MatchList(
            revision=store.revision,
            total=total,
            matches=[MatchSummary(**_summary(r, current)) for r in rows],
        )

    @router.get(
        "/matches/{id}",
        response_model=MatchDetail,
        responses={
            404: {"model": ErrorResponse, "description": "No such match."},
            **_UNAVAILABLE,
        },
        summary="One match with its final scoreboard",
    )
    async def get_match(id: int) -> MatchDetail:
        available()
        try:
            data = await store.get_match(id)
        except PlayerStoreError as exc:
            raise api_error(503, "players_unavailable", str(exc)) from exc
        if data is None:
            raise api_error(404, "match_not_found", f"no match {id}")
        return MatchDetail(
            **_summary(data, runtime.recorder.current_match_id),
            board_kept=data["board_kept"],
            scoreboard=_scoreboard(data),
        )

    return router
