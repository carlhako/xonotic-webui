"""Match actions: go to a map, skip the current map, restart the match (design D9, D10).

Each action is the game's own command. ``gotomap`` and ``endmatch`` are accepted but wait
while a dedicated server has auto-paused itself for being empty, so after sending one the
panel toggles ``pause`` through a hidden query when nobody is connected, and toggles it
back if the answer shows it had just paused a running server. A server with players is
never touched, so they see no pause messages.

An action is complete when the next ``:gamestart:`` is seen. The pending action and its
outcome are published on the status stream so every client sees it.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from xonotic_webui.colors import strip_colors
from xonotic_webui.console.console import Console, InternalQueryError
from xonotic_webui.events import GameStart
from xonotic_webui.logging import get_logger
from xonotic_webui.maps.catalogue import MapCatalogue
from xonotic_webui.serversettings.registry import GAMETYPES_BY_ID
from xonotic_webui.serversettings.serialize import validate_name
from xonotic_webui.status import StatusTracker
from xonotic_webui.supervisor import NotRunningError, RunState, Supervisor, SupervisorError

if TYPE_CHECKING:
    from collections.abc import Callable

log = get_logger("match-actions")

# The scoreboard (5 s), then a full map vote (the game requires under 50 s), then loading.
ACTION_TIMEOUT = 90.0
_PAUSE_REPLY_TIMEOUT = 5.0

_PAUSE_REPLY = re.compile(r"\b(?P<un>un)?paused the game\s*$")

_KINDS = ("goto", "skip", "restart")


class ActionInProgressError(SupervisorError):
    code = "action_in_progress"


class MapActionError(ValueError):
    code = "map_action_invalid"


class ActionMapNotInstalledError(MapActionError):
    code = "map_not_installed"


class ActionMapGametypeError(MapActionError):
    code = "map_unsupported_gametype"


@dataclass
class MatchAction:
    id: int
    kind: str  # goto | skip | restart
    map: str | None
    state: str = "pending"  # pending | done | timed_out

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "map": self.map, "state": self.state}


class PauseReplyCollector:
    """Collects the one ``<name> (un)paused the game`` line a ``pause`` produces."""

    def __init__(self) -> None:
        self.paused: bool | None = None

    @property
    def done(self) -> bool:
        return self.paused is not None

    def feed(self, raw_line: str) -> bool:
        if self.done:
            return False
        match = _PAUSE_REPLY.search(strip_colors(raw_line))
        if match is None:
            return False
        self.paused = match.group("un") is None
        return True


class MatchActions:
    def __init__(
        self,
        supervisor: Supervisor,
        console: Console,
        status: StatusTracker,
        catalogue: MapCatalogue,
        effective_gametype: Callable[[], str | None],
        *,
        timeout: float = ACTION_TIMEOUT,
        pause_timeout: float = _PAUSE_REPLY_TIMEOUT,
    ) -> None:
        self._sup = supervisor
        self._console = console
        self._status = status
        self._catalogue = catalogue
        self._effective_gametype = effective_gametype
        self._timeout = timeout
        self._pause_timeout = pause_timeout

        self._seq = 0
        self._current: MatchAction | None = None
        self._armed = False
        self._timer: asyncio.Task[None] | None = None

        status.add_match_listener(self._on_match_start)
        supervisor.subscribe_state(self._on_state)

    @property
    def current(self) -> MatchAction | None:
        return self._current

    # -- the actions -----------------------------------------------------------------
    async def goto(self, map_name: str) -> MatchAction:
        entry = self._catalogue.get(map_name)
        if entry is None:
            raise ActionMapNotInstalledError(f"the map {map_name!r} is not installed")
        gametype = self._effective_gametype()
        if gametype is not None and not entry.supports(gametype):
            name = GAMETYPES_BY_ID[gametype].name if gametype in GAMETYPES_BY_ID else gametype
            raise ActionMapGametypeError(f"{map_name} does not support {name}")
        try:
            validate_name(map_name)
        except ValueError as exc:
            raise ActionMapNotInstalledError(f"the map {map_name!r} is not installed") from exc
        return await self._run("goto", map_name, f"gotomap {map_name}", release_pause=True)

    async def skip(self) -> MatchAction:
        return await self._run("skip", None, "endmatch", release_pause=True)

    async def restart(self) -> MatchAction:
        # ``restart`` is not held up by an auto-paused server.
        return await self._run("restart", None, "restart", release_pause=False)

    # -- the shared sequence ---------------------------------------------------------
    async def _run(
        self, kind: str, map_name: str | None, command: str, *, release_pause: bool
    ) -> MatchAction:
        if self._sup.state is not RunState.RUNNING:
            raise NotRunningError("the server is not running")
        if self._current is not None and self._current.state == "pending":
            raise ActionInProgressError("a map action is already in progress")
        self._seq += 1
        action = MatchAction(id=self._seq, kind=kind, map=map_name)
        self._current = action
        self._armed = False
        self._publish()
        try:
            await self._console.submit_command(command)
        except Exception:
            self._drop(action)
            raise
        self._armed = True  # only matches that start from here on complete it
        self._timer = asyncio.create_task(self._expire(action), name="match-action-timeout")
        if release_pause and self._status.snapshot().human_count == 0:
            await self._release_pause()
        return action

    async def _release_pause(self) -> None:
        """Unpause an auto-paused empty server so the queued command can run (D10)."""
        try:
            reply = await self._console.query(
                "pause", PauseReplyCollector(), reply_timeout=self._pause_timeout
            )
            if reply.paused:
                # A running server: the toggle just paused it. Put it back.
                await self._console.query(
                    "pause", PauseReplyCollector(), reply_timeout=self._pause_timeout
                )
        except (InternalQueryError, SupervisorError) as exc:
            # The command stays queued and runs when someone joins; the action will
            # report that it did not complete.
            log.warning("could not unpause the server for a map action: %s", exc)

    # -- completion -------------------------------------------------------------------
    def _on_match_start(self, event: GameStart) -> None:
        action = self._current
        if action is None or action.state != "pending" or not self._armed:
            return
        if action.kind == "goto" and event.map != action.map:
            return  # another match started first; keep waiting for the requested one
        action.state = "done"
        self._cancel_timer()
        self._publish()

    async def _expire(self, action: MatchAction) -> None:
        await asyncio.sleep(self._timeout)
        if self._current is action and action.state == "pending":
            action.state = "timed_out"
            log.warning("map action %s (%s) did not complete in time", action.id, action.kind)
            self._publish()

    def _on_state(self, _frm: RunState, to: RunState) -> None:
        if to in (RunState.STOPPED, RunState.STARTING):
            self._cancel_timer()
            self._current = None
            self._armed = False

    def _drop(self, action: MatchAction) -> None:
        if self._current is action:
            self._current = None
        self._status.set_action(None)

    def _publish(self) -> None:
        self._status.set_action(self._current.to_dict() if self._current else None)

    def _cancel_timer(self) -> None:
        timer, self._timer = self._timer, None
        if timer is not None and not timer.done():
            timer.cancel()

    async def aclose(self) -> None:
        timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await timer
