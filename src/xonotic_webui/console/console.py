"""The console: live fan-out of server output to many clients and serialised relay of
operator commands to the server's stdin (server-console spec).

* On connect a client is given the retained history, then live output, with no gap and no
  duplication (sequence numbers bridge the two).
* Fan-out is per-subscriber and bounded: a slow or vanished client cannot stall the
  server or other clients.
* A submitted command is validated (one non-empty line), refused when the server is not
  running, and echoed to every client.
* The panel can also query the server on its own behalf via :meth:`Console.query`: the
  command is not echoed and the reply lines are withheld from client fan-out and from
  replayed history. This path is not reachable from the HTTP API.
* Standing filters (:meth:`Console.add_filter`) do the same for unsolicited blocks the
  server prints on its own, such as the end-of-match statistics report.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from typing import Protocol, TypeVar

from xonotic_webui.colors import strip_colors
from xonotic_webui.console.buffer import ConsoleBuffer, ConsoleLine, LineKind
from xonotic_webui.logging import get_logger
from xonotic_webui.supervisor import NotRunningError, RunState, Supervisor

log = get_logger("console")

_SUBSCRIBER_QUEUE_MAX = 4096
_DEFAULT_QUERY_TIMEOUT = 5.0
_MAX_COMMAND_LENGTH = 2000

LineMatcher = Callable[[str], bool]


class InvalidCommandError(ValueError):
    """The submitted command is not a single non-empty line."""

    code = "invalid_command"


class InternalQueryError(RuntimeError):
    """A panel-originated query got no reply of the expected shape in time."""

    code = "internal_query_failed"


class ReplyCollector(Protocol):
    """Consumes the lines of a reply. ``feed`` says whether a line was part of it."""

    @property
    def done(self) -> bool: ...

    def feed(self, raw_line: str) -> bool: ...


class LineCollector:
    """Collects the first single line whose colour-stripped text satisfies ``matcher``."""

    def __init__(self, matcher: LineMatcher) -> None:
        self._matcher = matcher
        self.line: str | None = None

    @property
    def done(self) -> bool:
        return self.line is not None

    def feed(self, raw_line: str) -> bool:
        if self.line is not None:
            return False
        if self._matcher(strip_colors(raw_line)):
            self.line = raw_line
            return True
        return False


class LineFilter(Protocol):
    """A standing filter. ``feed`` says whether a line belongs to a block to withhold."""

    def feed(self, raw_line: str) -> bool: ...


C = TypeVar("C", bound=ReplyCollector)


class _PendingQuery:
    __slots__ = ("collector", "future")

    def __init__(self, collector: ReplyCollector, future: asyncio.Future[None]) -> None:
        self.collector = collector
        self.future = future


class _Subscriber:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[ConsoleLine] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_MAX)
        self.dropped = 0

    def offer(self, line: ConsoleLine) -> None:
        try:
            self.queue.put_nowait(line)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
                self.dropped += 1
            self.queue.put_nowait(line)


def validate_command(command: str) -> str:
    """Return the command to send, or raise :class:`InvalidCommandError`."""
    if "\n" in command or "\r" in command:
        raise InvalidCommandError("a command must be a single line")
    stripped = command.strip()
    if not stripped:
        raise InvalidCommandError("a command must not be empty")
    if len(stripped) > _MAX_COMMAND_LENGTH:
        raise InvalidCommandError(f"a command must be at most {_MAX_COMMAND_LENGTH} characters")
    return stripped


class Console:
    def __init__(self, supervisor: Supervisor) -> None:
        self._sup = supervisor
        self._buffer: ConsoleBuffer = supervisor.console
        self._subscribers: set[_Subscriber] = set()
        self._command_lock = asyncio.Lock()
        self._pending: list[_PendingQuery] = []
        self._suppressed_seqs: set[int] = set()
        self._filters: list[LineFilter] = []
        self._buffer.add_listener(self._on_line)

    @property
    def buffer(self) -> ConsoleBuffer:
        return self._buffer

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def add_filter(self, line_filter: LineFilter) -> None:
        """Withhold, from clients and from replay, the lines ``line_filter`` consumes.

        The filter is fed every output line that no pending query consumed, before the
        line is fanned out.
        """
        self._filters.append(line_filter)

    # -- fan-out ---------------------------------------------------------
    def _on_line(self, line: ConsoleLine) -> None:
        if line.kind is LineKind.OUTPUT and self._pending:
            for pending in list(self._pending):
                if pending.future.done():
                    continue
                try:
                    consumed = pending.collector.feed(line.text)
                except Exception:
                    log.exception("query collector raised; passing the line through")
                    consumed = False
                if consumed:
                    self._suppressed_seqs.add(line.seq)
                    self._bound_suppressed()
                    if pending.collector.done:
                        pending.future.set_result(None)
                        self._discard(pending)
                    return  # withheld from client fan-out
        if line.kind is LineKind.OUTPUT and self._filters:
            for line_filter in list(self._filters):
                try:
                    consumed = line_filter.feed(line.text)
                except Exception:
                    log.exception("console filter raised; passing the line through")
                    consumed = False
                if consumed:
                    self._suppressed_seqs.add(line.seq)
                    self._bound_suppressed()
                    return
        for sub in list(self._subscribers):
            sub.offer(line)

    def _bound_suppressed(self) -> None:
        # Older lines have rolled out of the buffer and can never be replayed.
        if len(self._suppressed_seqs) > 1024:
            for seq in sorted(self._suppressed_seqs)[:-512]:
                self._suppressed_seqs.discard(seq)

    def _discard(self, pending: _PendingQuery) -> None:
        with contextlib.suppress(ValueError):
            self._pending.remove(pending)

    async def stream(self) -> AsyncIterator[ConsoleLine]:
        """Retained history followed by live output.

        Never raises if the server is stopped: the client waits and receives output once
        it starts. Sequence numbers make the history/live hand-over exact.
        """
        sub = _Subscriber()
        self._subscribers.add(sub)
        try:
            history = self._buffer.snapshot()
            last_seq = history[-1].seq if history else 0
            for line in history:
                if line.seq in self._suppressed_seqs:
                    continue
                yield line
            while True:
                line = await sub.queue.get()
                if line.seq <= last_seq:
                    continue  # already delivered as history
                last_seq = line.seq
                if line.seq in self._suppressed_seqs:
                    continue
                yield line
        finally:
            self._subscribers.discard(sub)

    # -- commands ----------------------------------------------------------
    async def submit_command(self, command: str) -> None:
        """Deliver an operator command to the server as if typed at its console."""
        command = validate_command(command)
        async with self._command_lock:
            # Reject before echoing so a rejected command never appears in the stream.
            if self._sup.state is not RunState.RUNNING:
                raise NotRunningError("the server is not running")
            self._buffer.add_command(command)
            await self._sup.send_command(command)

    async def query(
        self,
        command: str,
        collector: C,
        *,
        reply_timeout: float = _DEFAULT_QUERY_TIMEOUT,
    ) -> C:
        """Send a command on the panel's own behalf and wait for ``collector`` to finish.

        The command is not echoed and the lines the collector consumes are withheld from
        clients. Raises :class:`NotRunningError` if the server is not running (nothing is
        queued) and :class:`InternalQueryError` if the reply does not complete in time
        (the console and the server are left untouched).
        """
        command = validate_command(command)
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        pending = _PendingQuery(collector, future)
        async with self._command_lock:
            if self._sup.state is not RunState.RUNNING:
                raise NotRunningError("the server is not running")
            # Register before sending so a reply, which can only arrive afterwards,
            # cannot be missed.
            self._pending.append(pending)
            try:
                await self._sup.send_command(command)
            except Exception:
                self._discard(pending)
                raise
        try:
            await asyncio.wait_for(future, reply_timeout)
        except TimeoutError as exc:
            raise InternalQueryError(
                f"the server gave no reply of the expected shape within {reply_timeout:g}s"
            ) from exc
        finally:
            self._discard(pending)
        return collector

    async def query_line(
        self,
        command: str,
        matcher: LineMatcher,
        *,
        reply_timeout: float = _DEFAULT_QUERY_TIMEOUT,
    ) -> str:
        """``query`` for a single-line reply: the first line ``matcher`` accepts.

        ``matcher`` receives the colour-stripped line; the raw line is returned.
        """
        collector = await self.query(command, LineCollector(matcher), reply_timeout=reply_timeout)
        assert collector.line is not None
        return collector.line
