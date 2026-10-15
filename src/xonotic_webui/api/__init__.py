"""HTTP interface. The web interface uses exactly these routes; it has no privileged path."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

if TYPE_CHECKING:
    from xonotic_webui.runtime import Runtime

__all__ = ["build_api_router"]


def build_api_router(runtime: Runtime) -> APIRouter:
    from xonotic_webui.api.console import build_console_router
    from xonotic_webui.api.lifecycle import build_lifecycle_router
    from xonotic_webui.api.maps import build_maps_router
    from xonotic_webui.api.match import build_match_router
    from xonotic_webui.api.panel import build_panel_router
    from xonotic_webui.api.players import build_players_router
    from xonotic_webui.api.settings import build_settings_router
    from xonotic_webui.api.status import build_status_router

    router = APIRouter(prefix="/api")
    router.include_router(build_lifecycle_router(runtime))
    router.include_router(build_console_router(runtime))
    router.include_router(build_status_router(runtime))
    router.include_router(build_match_router(runtime))
    router.include_router(build_settings_router(runtime))
    router.include_router(build_maps_router(runtime))
    router.include_router(build_panel_router(runtime))
    router.include_router(build_players_router(runtime))
    return router
