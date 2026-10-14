"""Panel self-update routes: version, release check, upgrade (panel-self-update)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from xonotic_webui.api._shared import api_error
from xonotic_webui.api.schemas import ErrorResponse, PanelUpgradeRequest, PanelVersion
from xonotic_webui.selfupdate.upgrade import UpgradeError

if TYPE_CHECKING:
    from xonotic_webui.runtime import Runtime


def build_panel_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(prefix="/panel", tags=["panel"])

    def version() -> dict:
        return {
            **runtime.release_check.view(),
            "one_click_available": runtime.upgrade.helper_installed(),
            "manual_command": runtime.upgrade.manual_command(),
            "upgrade": runtime.upgrade.view(),
        }

    @router.get("/version", response_model=PanelVersion, summary="Panel version and update state")
    async def get_version() -> dict:
        return version()

    @router.post(
        "/check",
        response_model=PanelVersion,
        summary="Check for a newer panel release now",
    )
    async def check() -> dict:
        await runtime.release_check.check()
        return version()

    @router.post(
        "/upgrade",
        response_model=PanelVersion,
        responses={409: {"model": ErrorResponse, "description": "The upgrade was refused."}},
        summary="Upgrade the panel to the release it reported",
    )
    async def upgrade(body: PanelUpgradeRequest) -> dict:
        try:
            await runtime.upgrade.request(body.version)
        except UpgradeError as exc:
            raise api_error(409, exc.code, str(exc)) from exc
        return version()

    return router
