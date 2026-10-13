"""Status routes: the current snapshot and the change stream (server-status)."""

from __future__ import annotations

from contextlib import aclosing
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

from xonotic_webui.api._shared import EventStreamResponse, sse_response
from xonotic_webui.api.schemas import StatusModel

if TYPE_CHECKING:
    from xonotic_webui.runtime import Runtime


def build_status_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(prefix="/status", tags=["status"])

    @router.get("", response_model=StatusModel, summary="Current server status")
    async def status() -> dict:
        return runtime.status.snapshot().to_dict()

    @router.get(
        "/stream",
        response_class=EventStreamResponse,
        summary="Stream status changes (server-sent events; each event is a Status)",
        responses={
            200: {
                "model": StatusModel,
                "description": "An event stream; the first event is the current snapshot.",
            }
        },
    )
    async def status_stream(request: Request):
        async def snapshots():
            async with aclosing(runtime.status.stream()) as source:
                async for snap in source:
                    yield snap.to_dict()

        return sse_response(snapshots(), request)

    return router
