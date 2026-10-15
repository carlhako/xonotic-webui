"""The match watcher: polls the game once a second while someone is watching (design D2).

It is the only owner of the poll. The task runs while at least one subscriber is
connected to :meth:`MatchWatcher.stream` and the server is ``RUNNING``, and nothing is
sent to the game otherwise. A snapshot is published only when it differs from the last one
sent, so a paused server pushes nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from xonotic_webui.colors import strip_colors
from xonotic_webui.console.console import Console, InternalQueryError
from xonotic_webui.events import is_loaded_map
from xonotic_webui.logging import get_logger
from xonotic_webui.match.board import build_scoreboard
from xonotic_webui.match.clock import compute_clock, compute_score_limit, unavailable_clock
from xonotic_webui.match.reply import (
    LOGSCORES_BOTS_QUERY,
    MatchReply,
    MatchReplyCollector,
    parse_logscores_bots,
    poll_command,
)
from xonotic_webui.supervisor import NotRunningError, RunState, Supervisor, SupervisorError

log = get_logger("match")

# Server time that moved by less than this between two reads at least this far apart on the
# panel's clock means the server did not run: it is paused (design D4).
_PAUSE_MIN_WALL_SECONDS = 0.9
_PAUSE_MAX_ADVANCE = 0.05


def not_live_snapshot() -> dict[str, Any]:
    return {
        "live": False,
        "map": None,
        "gametype": None,
        "clock": unavailable_clock(),
        "score_limit": compute_score_limit(None, None),
        "scoreboard": build_scoreboard(None, []),
    }


class MatchWatcher:
    def __init__(
        self,
        supervisor: Supervisor,
        console: Console,
        *,
        known_match: Callable[[], tuple[str | None, str | None]] = lambda: (None, None),
        interval: float = 1.0,
        query_timeout: float = 3.0,
    ) -> None:
        """``known_match`` gives the (map, gametype) the status tracker knows, used when
        the dump does not name them."""
        self._sup = supervisor
        self._console = console
        self._known_match = known_match
        self._interval = interval
        self._query_timeout = query_timeout

        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._snapshot: dict[str, Any] = not_live_snapshot()
        self._task: asyncio.Task[None] | None = None
        self._logscores_bots = "0"
        self._prev_time: float | None = None
        self._prev_mono: float | None = None

        supervisor.subscribe_state(self._on_state)

    # -- snapshot and stream --------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        """The latest snapshot. It does not start polling."""
        return self._snapshot

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def polling(self) -> bool:
        return self._task is not None and not self._task.done()

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        """The current snapshot immediately, then one per change. Polls while subscribed."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        self._subscribers.add(queue)
        self._ensure_polling()
        try:
            yield self._snapshot
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)
            if not self._subscribers:
                self._stop_polling()

    def _publish(self, snapshot: dict[str, Any]) -> None:
        if snapshot == self._snapshot:
            return
        self._snapshot = snapshot
        for queue in list(self._subscribers):
            # Latest wins: a slow client only ever needs the newest snapshot.
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
            queue.put_nowait(snapshot)

    # -- lifecycle coupling ---------------------------------------------------------
    def _on_state(self, _frm: RunState, to: RunState) -> None:
        if to is RunState.RUNNING:
            self._ensure_polling()
        else:
            self._stop_polling()
            self._reset_clock_history()
            self._publish(not_live_snapshot())

    def _ensure_polling(self) -> None:
        if self.polling or not self._subscribers or self._sup.state is not RunState.RUNNING:
            return
        self._task = asyncio.get_running_loop().create_task(self._run(), name="match-watcher")

    def _stop_polling(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
        self._reset_clock_history()

    def _reset_clock_history(self) -> None:
        self._prev_time = None
        self._prev_mono = None

    async def aclose(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    # -- polling ---------------------------------------------------------------------
    async def _run(self) -> None:
        try:
            await self._read_logscores_bots()
            while self._sup.state is RunState.RUNNING:
                started = time.monotonic()
                if not await self._tick():
                    return
                await asyncio.sleep(max(0.0, self._interval - (time.monotonic() - started)))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("match polling stopped on an unexpected error")

    async def _read_logscores_bots(self) -> None:
        """The operator's value of ``sv_logscores_bots``, put back after each dump."""
        try:
            line = await self._console.query_line(
                LOGSCORES_BOTS_QUERY,
                lambda plain: parse_logscores_bots(plain) is not None,
                reply_timeout=self._query_timeout,
            )
        except (InternalQueryError, SupervisorError):
            return  # the game's default is used
        value = parse_logscores_bots(strip_colors(line))
        if value is not None:
            self._logscores_bots = value

    async def _tick(self) -> bool:
        """One poll. Returns False when polling must stop (the server is not running)."""
        try:
            collector = await self._console.query(
                poll_command(self._logscores_bots),
                MatchReplyCollector(),
                reply_timeout=self._query_timeout,
            )
        except NotRunningError:
            self._publish(not_live_snapshot())
            return False
        except (InternalQueryError, SupervisorError) as exc:
            log.debug("match poll got no reply: %s", exc)
            return True  # keep the last snapshot and try again
        if self._sup.state is not RunState.RUNNING:
            return False
        self._publish(self._build(collector.reply, time.monotonic()))
        return True

    def _paused(self, reply: MatchReply, now: float) -> bool:
        current = reply.globals.get("time")
        paused = False
        if current is not None and self._prev_time is not None and self._prev_mono is not None:
            advance = current - self._prev_time
            if (
                now - self._prev_mono >= _PAUSE_MIN_WALL_SECONDS
                and 0 <= advance < _PAUSE_MAX_ADVANCE
            ):
                paused = True
        if current is not None:
            self._prev_time, self._prev_mono = current, now
        return paused

    def _build(self, reply: MatchReply, now: float) -> dict[str, Any]:
        known_map, known_gametype = self._known_match()
        dump = reply.dump
        map_name = (dump.map if dump else None) or known_map
        gametype = (dump.gametype if dump else None) or known_gametype
        if map_name is None or not is_loaded_map(map_name):
            return not_live_snapshot()
        paused = self._paused(reply, now)
        return {
            "live": True,
            "map": map_name,
            "gametype": gametype,
            "clock": compute_clock(reply.globals, reply.timelimit, paused=paused),
            "score_limit": compute_score_limit(reply.fraglimit, gametype),
            "scoreboard": build_scoreboard(dump, reply.status_rows),
        }
