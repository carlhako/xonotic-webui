"""Lifecycle routes: start, stop, restart (server-lifecycle)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from xonotic_webui.api._shared import LIFECYCLE_ERROR_RESPONSES, http_error_from_supervisor
from xonotic_webui.api.schemas import StatusModel
from xonotic_webui.supervisor import SupervisorError

if TYPE_CHECKING:
    from xonotic_webui.runtime import Runtime


def build_lifecycle_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])

    def status() -> dict:
        return runtime.status.snapshot().to_dict()

    @router.post(
        "/start",
        response_model=StatusModel,
        responses=LIFECYCLE_ERROR_RESPONSES,
        summary="Start the server and wait until it is ready",
    )
    async def start() -> dict:
        try:
            await runtime.supervisor.start()
        except SupervisorError as exc:
            raise http_error_from_supervisor(exc) from exc
        return status()

    @router.post(
        "/stop",
        response_model=StatusModel,
        responses=LIFECYCLE_ERROR_RESPONSES,
        summary="Stop the server gracefully",
    )
    async def stop() -> dict:
        try:
            await runtime.supervisor.stop()
        except SupervisorError as exc:
            raise http_error_from_supervisor(exc) from exc
        return status()

    @router.post(
        "/restart",
        response_model=StatusModel,
        responses=LIFECYCLE_ERROR_RESPONSES,
        summary="Stop (if running) and start the server",
    )
    async def restart() -> dict:
        try:
            await runtime.supervisor.restart()
        except SupervisorError as exc:
            raise http_error_from_supervisor(exc) from exc
        return status()

    return router
