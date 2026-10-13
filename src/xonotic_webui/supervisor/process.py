"""Low-level ownership of the Xonotic dedicated server child process.

Exactly one process, with stdin and stdout held as pipes for its lifetime. stdin works as
a plain pipe (no pty needed, verified in the spike). stderr is merged into stdout so
nothing the server prints is lost.
"""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from xonotic_webui.logging import get_logger

log = get_logger("supervisor.process")


class XonoticProcess:
    def __init__(self, argv: Sequence[str], cwd: Path) -> None:
        self._argv = list(argv)
        self._cwd = cwd
        self._proc: asyncio.subprocess.Process | None = None
        self._stdin_lock = asyncio.Lock()

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    @property
    def returncode(self) -> int | None:
        return self._proc.returncode if self._proc else None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self) -> None:
        if self._proc is not None:
            raise RuntimeError("process already started")
        self._proc = await asyncio.create_subprocess_exec(
            *self._argv,
            cwd=str(self._cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=dict(os.environ),
            # Its own session: a signal aimed at the panel's process group (a terminal
            # ^C, a service reload) must not reach the game; only the panel stops it.
            start_new_session=True,
        )
        log.info("spawned dedicated server pid=%s", self._proc.pid)

    async def readlines(self) -> AsyncIterator[str]:
        """Yield decoded stdout lines until EOF.

        Drained continuously so the child never blocks on a full pipe.
        """
        assert self._proc is not None and self._proc.stdout is not None
        stream = self._proc.stdout
        while True:
            raw = await stream.readline()
            if not raw:
                break
            yield raw.decode("utf-8", errors="replace").rstrip("\r\n")

    async def write_line(self, text: str) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        data = (text.rstrip("\n") + "\n").encode("utf-8")
        async with self._stdin_lock:  # serialise concurrent writers
            self._proc.stdin.write(data)
            await self._proc.stdin.drain()

    async def wait(self) -> int:
        assert self._proc is not None
        return await self._proc.wait()

    def send_signal(self, sig: signal.Signals) -> None:
        if self._proc is not None and self._proc.returncode is None:
            self._proc.send_signal(sig)

    def kill(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            self._proc.kill()
