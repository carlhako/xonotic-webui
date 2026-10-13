"""Current server status, built from the event log and reconciled with ``status 1``.

Design D3/D4: the event log gives joins, parts, renames and match starts as they happen;
the tracker applies them to an in-memory model. A ``status 1`` query rebuilds the player
list when the server becomes ready and whenever a gap is suspected (a part or rename for
a player never seen). If the event log cannot be confirmed the snapshot says so instead
of presenting an empty roster as fact, and the roster is refreshed by polling.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict
from typing import Any

from xonotic_webui.colors import strip_colors
from xonotic_webui.console.console import Console, InternalQueryError
from xonotic_webui.events import (
    GameStart,
    PlayerJoin,
    PlayerName,
    PlayerPart,
    StatusReplyCollector,
    is_loaded_map,
    parse_event,
)
from xonotic_webui.logging import get_logger
from xonotic_webui.status.model import Player, StatusSnapshot
from xonotic_webui.supervisor import NotRunningError, RunState, Supervisor, SupervisorError

log = get_logger("status")

# How many times a roster refresh is repeated when events arrived while it was in flight.
_RECONCILE_ATTEMPTS = 3

_EVENTLOG_VALUE = re.compile(r'^"sv_eventlog" is "(?P<value>[^"]*)"')


class StatusTracker:
    def __init__(
        self,
        supervisor: Supervisor,
        console: Console,
        *,
        query_timeout: float = 5.0,
        poll_interval: float = 5.0,
    ) -> None:
        self._sup = supervisor
        self._console = console
        self._query_timeout = query_timeout
        self._poll_interval = poll_interval

        self._players: dict[int, Player] = {}  # by ent
        self._ent_by_id: dict[int, int] = {}
        self._map: str | None = None
        self._gametype: str | None = None
        self._event_log: str | None = None
        self._events_seen = False
        self._player_events = 0  # joins, parts and renames seen so far
        self._match_count = 0
        self._match_listeners: list[Callable[[GameStart], None]] = []
        self._action: dict[str, Any] | None = None

        self._subscribers: set[asyncio.Queue[StatusSnapshot]] = set()
        self._last_sent: dict | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._ready_task: asyncio.Task[None] | None = None
        self._reconcile_task: asyncio.Task[None] | None = None

        supervisor.set_line_sink(self.on_line)
        supervisor.subscribe_state(self._on_state)
        supervisor.subscribe_change(self._publish)

    # -- snapshot and stream --------------------------------------------------
    def snapshot(self) -> StatusSnapshot:
        crash = self._sup.last_crash
        failure = self._sup.last_start_failure
        return StatusSnapshot(
            state=self._sup.state.value,
            map=self._map,
            gametype=self._gametype,
            players=tuple(sorted(self._players.values(), key=lambda p: p.ent)),
            event_log=self._event_log,
            last_crash=asdict(crash) if crash else None,
            restart_abandoned=self._sup.restart_abandoned,
            last_start_failure=asdict(failure) if failure else None,
            action=dict(self._action) if self._action else None,
        )

    # -- match actions ----------------------------------------------------------------
    @property
    def match_count(self) -> int:
        """Matches started since the server started (every ``:gamestart:`` counts)."""
        return self._match_count

    def add_match_listener(self, listener: Callable[[GameStart], None]) -> None:
        """Call ``listener`` for every match start, including a restart of the same map."""
        self._match_listeners.append(listener)

    def set_action(self, action: dict[str, Any] | None) -> None:
        """Publish the latest match action (or clear it) to every client."""
        self._action = dict(action) if action else None
        self._publish()

    async def stream(self) -> AsyncIterator[StatusSnapshot]:
        """The current snapshot immediately, then one per change."""
        queue: asyncio.Queue[StatusSnapshot] = asyncio.Queue(maxsize=1)
        self._subscribers.add(queue)
        try:
            yield self.snapshot()
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def _publish(self) -> None:
        snap = self.snapshot()
        as_dict = snap.to_dict()
        if as_dict == self._last_sent:
            return
        self._last_sent = as_dict
        for queue in list(self._subscribers):
            # Latest wins: a slow client only ever needs the newest snapshot.
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
            queue.put_nowait(snap)

    # -- event application ------------------------------------------------------
    def on_line(self, raw_line: str) -> None:
        event = parse_event(raw_line)
        if event is None:
            return
        self._events_seen = True
        changed = False
        if isinstance(event, GameStart):
            changed = self._map != event.map or self._gametype != event.gametype
            self._map, self._gametype = event.map, event.gametype
            self._match_count += 1
            for listener in list(self._match_listeners):
                try:
                    listener(event)
                except Exception:
                    log.exception("match listener raised; continuing")
        elif isinstance(event, PlayerJoin):
            self._player_events += 1
            self._drop_id(event.player_id)
            old = self._players.get(event.ent)
            if old is not None and old.id is not None:
                self._ent_by_id.pop(old.id, None)  # the slot was reused: we missed a part
            self._players[event.ent] = Player(
                ent=event.ent, name=event.name, bot=event.bot, id=event.player_id
            )
            self._ent_by_id[event.player_id] = event.ent
            changed = True
        elif isinstance(event, PlayerName):
            self._player_events += 1
            player = self._player_by_id(event.player_id)
            if player is None:
                self._request_reconcile()
            elif player.name != event.name:
                player.name = event.name
                changed = True
        elif isinstance(event, PlayerPart):
            self._player_events += 1
            ent = self._ent_by_id.pop(event.player_id, None)
            if ent is None or self._players.pop(ent, None) is None:
                self._request_reconcile()
            else:
                changed = True
        if changed:
            self._publish()

    def _player_by_id(self, player_id: int) -> Player | None:
        ent = self._ent_by_id.get(player_id)
        return self._players.get(ent) if ent is not None else None

    def _drop_id(self, player_id: int) -> None:
        ent = self._ent_by_id.pop(player_id, None)
        if ent is not None:
            self._players.pop(ent, None)

    # -- lifecycle coupling --------------------------------------------------------
    def _on_state(self, _frm: RunState, to: RunState) -> None:
        if to in (RunState.STOPPED, RunState.STARTING):
            self._cancel(self._ready_task)
            self._cancel(self._reconcile_task)
            self._clear()
        if to is RunState.RUNNING:
            self._ready_task = self._spawn(self._on_ready(), "status-ready")
        self._publish()

    def _clear(self) -> None:
        self._players.clear()
        self._ent_by_id.clear()
        self._map = None
        self._gametype = None
        self._event_log = None
        self._events_seen = False
        self._match_count = 0
        self._action = None

    def _spawn(self, coro, name: str) -> asyncio.Task[None]:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    @staticmethod
    def _cancel(task: asyncio.Task[None] | None) -> None:
        if task is not None and not task.done():
            task.cancel()

    async def aclose(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # -- readiness work --------------------------------------------------------------
    async def _on_ready(self) -> None:
        """Re-assert and confirm the event log, then reconcile the roster."""
        try:
            await self._confirm_event_log()
            self._publish()
            await self._reconcile()
            if self._event_log == "unavailable":
                await self._poll_roster()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("post-readiness status work failed")

    async def _confirm_event_log(self) -> None:
        # Belt and braces (design D3): the wrapper config already forced it on; this makes
        # sure, and proves it, so an operator is told when it is not working.
        with contextlib.suppress(SupervisorError):
            await self._sup.send_command("sv_eventlog 1")
            await self._sup.send_command("sv_eventlog_console 1")
        try:
            reply = await self._console.query_line(
                "sv_eventlog",
                lambda plain: _EVENTLOG_VALUE.match(plain) is not None,
                reply_timeout=self._query_timeout,
            )
        except (InternalQueryError, SupervisorError):
            # No answer; trust the evidence of lines already seen.
            self._event_log = "enabled" if self._events_seen else "unavailable"
            return
        match = _EVENTLOG_VALUE.match(strip_colors(reply))
        value = match.group("value") if match else "0"
        self._event_log = "enabled" if value == "1" or self._events_seen else "unavailable"
        if self._event_log == "unavailable":
            log.warning("the server's event log is not enabled; player tracking is degraded")

    def _request_reconcile(self) -> None:
        if self._reconcile_task is not None and not self._reconcile_task.done():
            return
        if self._sup.state is not RunState.RUNNING:
            return
        self._reconcile_task = self._spawn(self._reconcile_soon(), "status-reconcile")

    async def _reconcile_soon(self) -> None:
        await asyncio.sleep(0.05)  # let a burst of related events land first
        with contextlib.suppress(asyncio.CancelledError):
            await self._reconcile()

    async def _reconcile(self) -> None:
        """Rebuild the roster (and the map) from a ``status 1`` reply.

        The reply is applied after the event loop has had a chance to process lines that
        arrived behind it. If a join, part or rename was seen while the query was in
        flight, the reply may predate it and would silently undo it, so ask again (a few
        times at most).
        """
        for attempt in range(_RECONCILE_ATTEMPTS):
            seen = self._player_events
            try:
                reply = await self._console.query(
                    "status 1", StatusReplyCollector(), reply_timeout=self._query_timeout
                )
            except NotRunningError:
                return  # the server stopped under us (a stop raced the post-start work)
            except (InternalQueryError, SupervisorError) as exc:
                log.warning("status reconcile failed: %s", exc)
                return
            if self._sup.state is not RunState.RUNNING:
                return
            if self._player_events != seen and attempt < _RECONCILE_ATTEMPTS - 1:
                continue
            self._apply_status_reply(reply)
            return

    def _apply_status_reply(self, reply: StatusReplyCollector) -> None:
        players: dict[int, Player] = {}
        for row in reply.rows:
            known = self._players.get(row.ent)
            keep_id = known.id if known is not None and known.bot == row.bot else None
            players[row.ent] = Player(ent=row.ent, name=row.name, bot=row.bot, id=keep_id)
        self._players = players
        self._ent_by_id = {p.id: p.ent for p in players.values() if p.id is not None}
        if reply.map and is_loaded_map(reply.map):
            if self._map != reply.map:
                self._gametype = None  # a different match: its gametype is not known
            self._map = reply.map
        self._publish()

    async def _poll_roster(self) -> None:
        while self._sup.state is RunState.RUNNING:
            await asyncio.sleep(self._poll_interval)
            await self._reconcile()
