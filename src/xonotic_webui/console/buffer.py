"""Bounded in-memory buffer of recent console output (server-console spec).

* Memory is bounded: at most ``maxlen`` entries are kept, oldest discarded first.
* History survives a server restart while the panel keeps running; the boundary between
  runs is a ``marker`` entry.
* Every entry has a monotonic sequence number so a client connecting mid-session is
  given history and live lines with no gap and no duplicate.
* Each entry carries the colour-stripped form (``plain``) for matching; ``text`` is the
  raw line the browser colours itself.
"""

from __future__ import annotations

import enum
import itertools
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from xonotic_webui.colors import strip_colors
from xonotic_webui.logging import get_logger

log = get_logger("console.buffer")


class LineKind(enum.StrEnum):
    OUTPUT = "output"  # a line from the server
    COMMAND = "command"  # a command an operator submitted (echoed)
    MARKER = "marker"  # a run boundary, e.g. the server was restarted


@dataclass(frozen=True)
class ConsoleLine:
    seq: int
    kind: LineKind
    text: str
    plain: str


class ConsoleBuffer:
    def __init__(self, maxlen: int) -> None:
        self._lines: deque[ConsoleLine] = deque(maxlen=maxlen)
        self._counter = itertools.count(1)
        self._listeners: list[Callable[[ConsoleLine], None]] = []

    def add_listener(self, listener: Callable[[ConsoleLine], None]) -> Callable[[], None]:
        """Register a callback fired on every appended line; returns an unsubscribe."""
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @property
    def maxlen(self) -> int:
        assert self._lines.maxlen is not None
        return self._lines.maxlen

    def __len__(self) -> int:
        return len(self._lines)

    def _append(self, kind: LineKind, text: str) -> ConsoleLine:
        line = ConsoleLine(seq=next(self._counter), kind=kind, text=text, plain=strip_colors(text))
        self._lines.append(line)
        for listener in list(self._listeners):
            try:
                listener(line)
            except Exception:  # a bad listener must not corrupt the buffer
                log.exception("console listener raised")
        return line

    def add_output(self, text: str) -> ConsoleLine:
        return self._append(LineKind.OUTPUT, text)

    def add_command(self, text: str) -> ConsoleLine:
        return self._append(LineKind.COMMAND, text)

    def add_marker(self, text: str) -> ConsoleLine:
        return self._append(LineKind.MARKER, text)

    def snapshot(self, after_seq: int = 0) -> list[ConsoleLine]:
        """Retained lines with ``seq > after_seq``, oldest first."""
        return [line for line in self._lines if line.seq > after_seq]

    def last_seq(self) -> int:
        return self._lines[-1].seq if self._lines else 0
