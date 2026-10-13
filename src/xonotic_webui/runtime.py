"""Runtime wiring: one supervisor, console and status tracker per process."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from xonotic_webui.console.console import Console
from xonotic_webui.logging import get_logger
from xonotic_webui.maps.actions import MatchActions
from xonotic_webui.maps.catalogue import MapCatalogue
from xonotic_webui.maps.control import MapControl
from xonotic_webui.serversettings.service import ServerSettingsService
from xonotic_webui.serversettings.store import SettingsStore
from xonotic_webui.settings import Settings
from xonotic_webui.status import StatusTracker
from xonotic_webui.supervisor import Supervisor

if TYPE_CHECKING:
    from fastapi import FastAPI

log = get_logger("runtime")


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.supervisor = Supervisor(settings)
        self.console = Console(self.supervisor)
        self.status = StatusTracker(self.supervisor, self.console)
        self.map_catalogue = MapCatalogue(settings.game_root, settings.userdir)
        self.server_settings = ServerSettingsService(
            settings,
            self.supervisor,
            self.console,
            SettingsStore(settings.game_settings_file),
            map_gametypes=self.map_catalogue.gametype_map,
        )
        # The config generated from the saved settings is rewritten at every start.
        self.supervisor.set_settings_cfg(self.server_settings.render_config)
        self.map_control = MapControl(
            self.server_settings, self.map_catalogue, lambda: self.status.snapshot().gametype
        )
        self.match_actions = MatchActions(
            self.supervisor,
            self.console,
            self.status,
            self.map_catalogue,
            self.map_control.effective_gametype,
        )
        self._restore_task: asyncio.Task[None] | None = None

    def effective_gametype(self) -> str | None:
        """The gametype the next map is played as: the operator's choice, else the running one."""
        return self.map_control.effective_gametype()

    def attach(self, app: FastAPI) -> None:
        from xonotic_webui.api import build_api_router

        app.include_router(build_api_router(self))

    async def startup(self) -> None:
        # Restore in the background so the web interface is up while the server starts.
        self._restore_task = asyncio.create_task(self.supervisor.restore(), name="xonotic-restore")

    async def shutdown(self) -> None:
        # Stop the game server cleanly before the panel goes away (no orphan).
        await self.supervisor.aclose()
        if self._restore_task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._restore_task
        await self.match_actions.aclose()
        await self.status.aclose()
