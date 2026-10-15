"""Live match routes: the current snapshot and the change stream (live-match)."""

from __future__ import annotations

from contextlib import aclosing
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

from xonotic_webui.api._shared import EventStreamResponse, sse_response
from xonotic_webui.api.schemas import MatchModel

if TYPE_CHECKING:
    from xonotic_webui.runtime import Runtime


def build_match_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(prefix="/match", tags=["match"])

    @router.get(
        "",
        response_model=MatchModel,
        summary="The latest live match state (does not start polling the game)",
    )
    async def match() -> dict:
        return runtime.match.snapshot()

    @router.get(
        "/stream",
        response_class=EventStreamResponse,
        summary="Stream the live match state (server-sent events; each event is a Match)",
        responses={
            200: {
                "model": MatchModel,
                "description": (
                    "An event stream; the first event is the current state. Reading it makes "
                    "the panel poll the game about once a second until the last reader leaves."
                ),
            }
        },
    )
    async def match_stream(request: Request):
        async def snapshots():
            async with aclosing(runtime.match.stream()) as source:
                async for snap in source:
                    yield snap

        return sse_response(snapshots(), request)

    return router
