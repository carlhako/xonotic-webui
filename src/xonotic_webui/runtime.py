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
from xonotic_webui.maps.favourites import FavouritesStore
from xonotic_webui.maps.packages import PackageStore
from xonotic_webui.players.recorder import PlayerRecorder
from xonotic_webui.players.report import StatsReportFilter
from xonotic_webui.players.store import PlayerStore
from xonotic_webui.selfupdate.release_check import ReleaseChecker
from xonotic_webui.selfupdate.upgrade import UpgradeService
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
        # The end-of-match statistics report is for the panel, not for the console tab.
        self.console.add_filter(StatsReportFilter())
        self.status = StatusTracker(self.supervisor, self.console)
        self.players_store = PlayerStore(settings.players_db)
        self.recorder = PlayerRecorder(self.supervisor, self.console, self.players_store)
        self.map_catalogue = MapCatalogue(settings.game_root, settings.userdir)
        # The game scans its packages when it starts; the catalogue notes which it had.
        self.supervisor.subscribe_state(self.map_catalogue.on_state)
        self.package_store = PackageStore(settings.userdir / "data", self.map_catalogue)
        self.favourites = FavouritesStore(settings.favourites_file)
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
        self.release_check = ReleaseChecker(settings)
        self.upgrade = UpgradeService(settings, self.supervisor, self.release_check)
        self._restore_task: asyncio.Task[None] | None = None

    def effective_gametype(self) -> str | None:
        """The gametype the next map is played as: the operator's choice, else the running one."""
        return self.map_control.effective_gametype()

    def attach(self, app: FastAPI) -> None:
        from xonotic_webui.api import build_api_router

        app.include_router(build_api_router(self))

    async def startup(self) -> None:
        # A crash mid-upload can leave a temp file; it is never a package, so just remove it.
        self.package_store.clean_stale_uploads()
        # Player history: opening the database is quick, and a failure only turns the
        # history off (it is logged, and the rest of the panel is unaffected).
        await self.recorder.start()
        # Restore in the background so the web interface is up while the server starts.
        self._restore_task = asyncio.create_task(self.supervisor.restore(), name="xonotic-restore")
        # The first release check waits in its own task; it never delays the above.
        self.release_check.start()
        # An upgrade requested before this start (the helper restarted the panel to install
        # it) is followed to its outcome.
        self.upgrade.start()

    async def shutdown(self) -> None:
        # Stop the game server cleanly before the panel goes away (no orphan).
        await self.upgrade.stop()
        await self.release_check.stop()
        await self.supervisor.aclose()
        if self._restore_task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._restore_task
        # After the server has stopped: everything pending is written, then the file closed.
        await self.recorder.aclose()
        await self.match_actions.aclose()
        await self.status.aclose()
