"""Runtime wiring: one supervisor, console and status tracker per process."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from xonotic_webui.console.console import Console
from xonotic_webui.logging import get_logger
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
        self._restore_task: asyncio.Task[None] | None = None

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
        await self.status.aclose()
