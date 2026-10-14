"""The Xonotic server supervisor.

Owns exactly one server process at a time, drives it through the four-state lifecycle
model, and guarantees a clean shutdown path. Everything else in the panel observes the
server through this object.

Concurrency model: every state-changing method runs on the event loop and the
operator-facing ones (``start``, ``stop``, ``restart``) take ``_op_lock`` so that at most
one lifecycle operation is in flight. A request that arrives while one is in flight is
rejected, not queued (server-lifecycle: "Conflicting operations are rejected").

Run ownership: each spawn is a :class:`_Run` with its own pump (stdout reader) and watcher
(waits for exit). The watcher classifies an exit: requested (the stop path owns the
state), during startup (the start path owns it), or a crash while running (handled here
by recording it, going to ``stopped`` and, within bounds, starting again).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from xonotic_webui.console.buffer import ConsoleBuffer
from xonotic_webui.events import GameStart, is_loaded_map, is_map_line, parse_event
from xonotic_webui.logging import get_logger
from xonotic_webui.serversettings.registry import FORCED_CVARS
from xonotic_webui.serversettings.store import CONFIG_HEADER
from xonotic_webui.settings import APP_NAME, Settings
from xonotic_webui.supervisor.process import XonoticProcess
from xonotic_webui.supervisor.state import RunState, StateListener, StateMachine

__all__ = [
    "SETTINGS_CONFIG_NAME",
    "WRAPPER_CONFIG_NAME",
    "AlreadyRunningError",
    "CrashInfo",
    "NoInstallationError",
    "NotRunningError",
    "ReadinessTimeoutError",
    "StartFailedError",
    "StartFailure",
    "Supervisor",
    "SupervisorError",
    "TransitionInProgressError",
]

log = get_logger("supervisor")

LineSink = Callable[[str], None]

# The panel-owned config the server is launched with (bootstrap design D3). It runs the
# operator's server.cfg, then the panel's generated settings (config-and-maps D1), and
# only then forces what the panel depends on, so neither a user config nor a panel
# setting can turn the event log off or the console colours back into ANSI escapes.
WRAPPER_CONFIG_NAME = f"{APP_NAME}.cfg"
SETTINGS_CONFIG_NAME = f"{APP_NAME}-settings.cfg"
_WRAPPER_CONFIG = (
    f"// Managed by {APP_NAME}: rewritten on every start, do not edit.\n"
    "// Run the operator's configuration, then the panel's settings, then force what the\n"
    "// panel depends on.\n"
    "exec server.cfg\n"
    f"exec {SETTINGS_CONFIG_NAME}\n" + "".join(f"{name} {value}\n" for name, value in FORCED_CVARS)
)

# After a quit that is not honoured: SIGTERM, wait this long, then SIGKILL.
_TERM_GRACE = 5.0
_KILL_WAIT = 10.0
# How long to wait for the stdout pump to hit EOF once the process has exited.
_DRAIN_TIMEOUT = 5.0


class SupervisorError(RuntimeError):
    """Base class for lifecycle errors, with a stable ``code``."""

    code = "supervisor_error"


class AlreadyRunningError(SupervisorError):
    code = "already_running"


class NotRunningError(SupervisorError):
    code = "not_running"


class TransitionInProgressError(SupervisorError):
    code = "transition_in_progress"


class NoInstallationError(SupervisorError):
    code = "game_not_installed"


class ReadinessTimeoutError(SupervisorError):
    code = "readiness_timeout"


class StartFailedError(SupervisorError):
    code = "start_failed"


@dataclass(frozen=True)
class CrashInfo:
    at: str  # ISO 8601 UTC
    exit_code: int | None


@dataclass(frozen=True)
class StartFailure:
    at: str  # ISO 8601 UTC
    reason: str
    exit_code: int | None = None


@dataclass
class _Run:
    proc: XonoticProcess
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    exited: asyncio.Event = field(default_factory=asyncio.Event)
    exit_code: int | None = None
    stop_requested: bool = False
    pump: asyncio.Task[None] | None = None
    watcher: asyncio.Task[None] | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def write_userdir_config(settings: Settings, name: str, text: str) -> Path:
    """Atomically write ``text`` as ``userdir/data/<name>``; returns the path."""
    data_dir = settings.userdir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / name
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)
    return path


class Supervisor:
    def __init__(
        self,
        settings: Settings,
        *,
        line_sink: LineSink | None = None,
        clock: Callable[[], float] = time.monotonic,
        probe_after: float = 8.0,
        probe_interval: float = 2.0,
        settings_cfg: Callable[[], str] | None = None,
    ) -> None:
        self._settings = settings
        # Renders the panel-owned settings config at every start. Without one the file is
        # header-only, which changes nothing.
        self._settings_cfg = settings_cfg
        self._sink = line_sink
        self._clock = clock
        self._probe_after = probe_after
        self._probe_interval = probe_interval

        self._sm = StateMachine(RunState.STOPPED)
        self._op_lock = asyncio.Lock()
        self._run: _Run | None = None
        self._recovery_task: asyncio.Task[None] | None = None
        self._closing = False
        self._closing_event = asyncio.Event()

        self._last_crash: CrashInfo | None = None
        self._last_start_failure: StartFailure | None = None
        self._restart_abandoned = False
        self._crash_times: list[float] = []

        self._change_listeners: list[Callable[[], None]] = []
        self.console = ConsoleBuffer(settings.console_buffer_lines)

    # -- observation ------------------------------------------------------
    @property
    def state(self) -> RunState:
        return self._sm.state

    @property
    def last_crash(self) -> CrashInfo | None:
        return self._last_crash

    @property
    def last_start_failure(self) -> StartFailure | None:
        return self._last_start_failure

    @property
    def restart_abandoned(self) -> bool:
        return self._restart_abandoned

    @property
    def pid(self) -> int | None:
        return self._run.proc.pid if self._run is not None else None

    @property
    def is_closing(self) -> bool:
        return self._closing

    def subscribe_state(self, listener: StateListener) -> None:
        self._sm.subscribe(listener)

    def subscribe_change(self, listener: Callable[[], None]) -> None:
        """Fired when observable facts other than the state change (crash, abandoned)."""
        self._change_listeners.append(listener)

    def set_line_sink(self, sink: LineSink) -> None:
        self._sink = sink

    def set_settings_cfg(self, render: Callable[[], str]) -> None:
        """Provide what the generated settings config contains at every start."""
        self._settings_cfg = render

    def _notify_change(self) -> None:
        for listener in list(self._change_listeners):
            try:
                listener()
            except Exception:
                log.exception("change listener raised; continuing")

    # -- guards ------------------------------------------------------------
    def _installed(self) -> bool:
        binary = self._settings.game_binary
        return binary.is_file()

    def transition_in_progress(self) -> bool:
        """Whether a start, stop or restart is under way (or its lock is held)."""
        return self._sm.state in (RunState.STARTING, RunState.STOPPING) or self._op_lock.locked()

    def _reject_if_closing(self) -> None:
        if self._closing:
            raise TransitionInProgressError("the panel is shutting down")

    # -- lifecycle: start ----------------------------------------------------
    async def start(self) -> None:
        self._reject_if_closing()
        state = self._sm.state
        if state in (RunState.STARTING, RunState.RUNNING):
            raise AlreadyRunningError("the server is already running")
        if self.transition_in_progress():
            raise TransitionInProgressError("a lifecycle operation is in progress")
        async with self._op_lock:
            self._reject_if_closing()
            if self._sm.state is not RunState.STOPPED:
                raise AlreadyRunningError("the server is already running")
            await self._cancel_recovery()
            await self._start_locked(operator=True)

    async def _start_locked(self, *, operator: bool) -> None:
        if not self._installed():
            raise NoInstallationError(
                f"the game is not installed: {self._settings.game_binary} not found"
            )
        self._sm.transition(RunState.STARTING)
        if operator:
            self._restart_abandoned = False
            self._notify_change()
        try:
            run = await self._spawn()
        except OSError as exc:
            self._sm.transition(RunState.STOPPED)
            self._record_start_failure(f"could not launch the server: {exc}", None)
            if operator:
                self._persist_desired(running=False)
            raise StartFailedError(f"could not launch the server: {exc}") from exc

        try:
            await self._await_ready(run)
        except SupervisorError:
            # The run is already torn down and the state is back to stopped.
            if operator:
                self._persist_desired(running=False)
            raise

        self._sm.transition(RunState.RUNNING)
        self._restart_abandoned = False
        self._last_start_failure = None
        self._notify_change()
        if operator:
            self._persist_desired(running=True)

    def _write_wrapper_config(self) -> None:
        write_userdir_config(self._settings, WRAPPER_CONFIG_NAME, _WRAPPER_CONFIG)

    def _write_settings_config(self) -> None:
        text = CONFIG_HEADER
        if self._settings_cfg is not None:
            try:
                text = self._settings_cfg()
            except Exception as exc:
                # An unreadable settings store must not keep the server from starting.
                log.exception("could not generate the settings config")
                self.console.add_marker(f"— panel settings not applied: {exc} —")
        write_userdir_config(self._settings, SETTINGS_CONFIG_NAME, text)

    def _argv(self) -> list[str]:
        s = self._settings
        return [
            str(s.game_binary),
            "-userdir",
            str(s.userdir),
            "+port",
            str(s.game_port),
            "+sys_colortranslation",
            "2",
            "+serverconfig",
            WRAPPER_CONFIG_NAME,
        ]

    async def _spawn(self) -> _Run:
        self._write_settings_config()
        self._write_wrapper_config()
        # Mark the run boundary so a restart is distinguishable within the history.
        if len(self.console) > 0:
            self.console.add_marker("— server starting —")
        proc = XonoticProcess(self._argv(), self._settings.game_root)
        await proc.start()
        run = _Run(proc)
        self._run = run
        run.pump = asyncio.create_task(self._pump(run), name="xonotic-stdout-pump")
        run.watcher = asyncio.create_task(self._watch(run), name="xonotic-watcher")
        return run

    async def _await_ready(self, run: _Run) -> None:
        """Wait for readiness; on any failure tear the run down and raise."""
        probe = asyncio.create_task(self._probe_readiness(run), name="xonotic-ready-probe")
        waiters = {
            asyncio.create_task(run.ready.wait()),
            asyncio.create_task(run.exited.wait()),
            asyncio.create_task(self._closing_event.wait()),
        }
        try:
            await asyncio.wait(
                waiters,
                timeout=self._settings.readiness_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in (*waiters, probe):
                task.cancel()
            await asyncio.gather(*waiters, probe, return_exceptions=True)

        if run.exited.is_set():
            reason = f"the server exited during startup (status {run.exit_code})"
            await self._abort_start(run, reason, exit_code=run.exit_code)
            raise StartFailedError(reason)
        if run.ready.is_set():
            return
        if self._closing:
            await self._abort_start(run, "the panel is shutting down", exit_code=None)
            raise TransitionInProgressError("the panel is shutting down")
        timeout = self._settings.readiness_timeout
        reason = f"the server did not become ready within {timeout:g}s"
        await self._abort_start(run, reason, exit_code=None, terminate=True)
        raise ReadinessTimeoutError(reason)

    async def _abort_start(
        self, run: _Run, reason: str, *, exit_code: int | None, terminate: bool = False
    ) -> None:
        log.error("start failed: %s", reason)
        run.stop_requested = True  # an exit from here on is ours, not a crash
        if terminate or run.proc.running:
            await self._shutdown_process(run, graceful=False)
        await self._drain(run)
        self._run = None
        self.console.add_marker(f"— start failed: {reason} —")
        self._record_start_failure(reason, exit_code)
        with contextlib.suppress(Exception):
            self._sm.transition(RunState.STOPPED)

    def _record_start_failure(self, reason: str, exit_code: int | None) -> None:
        self._last_start_failure = StartFailure(at=_now(), reason=reason, exit_code=exit_code)
        self._notify_change()

    async def _probe_readiness(self, run: _Run) -> None:
        """Fallback readiness signal (design D8).

        The normal signal is the first ``:gamestart:`` line. If the event log is
        unavailable it never comes, so after a few seconds ask the server directly: a
        ``status`` reply naming a real map means it is up.
        """
        await asyncio.sleep(self._probe_after)
        while not run.ready.is_set() and not run.exited.is_set():
            with contextlib.suppress(Exception):
                await run.proc.write_line("status 1")
            await asyncio.sleep(self._probe_interval)

    async def _pump(self, run: _Run) -> None:
        """Always-draining stdout reader; never blocks the child on output consumption."""
        try:
            async for line in run.proc.readlines():
                self.console.add_output(line)
                if self._sink is not None:
                    try:
                        self._sink(line)
                    except Exception:
                        log.exception("line sink raised; continuing")
                if not run.ready.is_set() and self._is_ready_line(line):
                    run.ready.set()
        except Exception:
            log.exception("stdout pump failed")

    @staticmethod
    def _is_ready_line(raw: str) -> bool:
        if isinstance(parse_event(raw), GameStart):
            return True
        # Fallback: a status reply naming a loaded map.
        from xonotic_webui.colors import strip_colors

        name = is_map_line(strip_colors(raw))
        return name is not None and is_loaded_map(name)

    async def _watch(self, run: _Run) -> None:
        code = await run.proc.wait()
        if run.pump is not None:
            with contextlib.suppress(asyncio.CancelledError, TimeoutError, Exception):
                await asyncio.wait_for(asyncio.shield(run.pump), timeout=_DRAIN_TIMEOUT)
        run.exit_code = code
        run.exited.set()
        log.info("server exited status=%s requested=%s", code, run.stop_requested)

        if run.stop_requested or self._run is not run:
            return  # the stop or start path owns the state
        if self._sm.state is not RunState.RUNNING:
            return  # exit during startup: the start path owns it

        # An unexpected exit while running: record it, go to stopped, recover within bounds.
        self._last_crash = CrashInfo(at=_now(), exit_code=code)
        self._run = None
        self.console.add_marker(f"— server exited unexpectedly (status {code}) —")
        with contextlib.suppress(Exception):
            self._sm.transition(RunState.STOPPED)
        self._notify_change()
        self._begin_recovery()

    # -- crash recovery -----------------------------------------------------
    def _begin_recovery(self) -> None:
        if self._closing:
            return
        self._recovery_task = asyncio.create_task(self._recover(), name="xonotic-recovery")

    async def _cancel_recovery(self) -> None:
        task = self._recovery_task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._recovery_task = None

    async def _recover(self) -> None:
        threshold = self._settings.crash_restart_threshold
        window = self._settings.crash_restart_window
        while True:
            now = self._clock()
            self._crash_times = [t for t in self._crash_times if now - t <= window]
            self._crash_times.append(now)

            if threshold <= 0:
                log.warning("automatic restart is disabled; leaving the server stopped")
                return
            if len(self._crash_times) > threshold:
                log.error(
                    "%d crashes within %gs exceeds the threshold of %d; abandoning restart",
                    len(self._crash_times),
                    window,
                    threshold,
                )
                self._restart_abandoned = True
                self.console.add_marker("— automatic restart abandoned after repeated crashes —")
                self._notify_change()
                return

            log.warning("restarting after a crash (%d/%d)", len(self._crash_times), threshold)
            self.console.add_marker("— restarting after a crash —")
            await asyncio.sleep(self._settings.crash_restart_delay)
            if self._closing:
                return
            async with self._op_lock:
                if self._closing or self._sm.state is not RunState.STOPPED:
                    return
                try:
                    await self._start_locked(operator=False)
                except SupervisorError as exc:
                    # A failed attempt counts as another crash and is bounded the same way.
                    log.error("automatic restart failed: %s", exc)
                    continue
            return

    # -- lifecycle: stop -----------------------------------------------------
    async def stop(self) -> None:
        self._reject_if_closing()
        state = self._sm.state
        if state is RunState.STOPPED and not self._op_lock.locked():
            raise NotRunningError("the server is not running")
        if self.transition_in_progress():
            raise TransitionInProgressError("a lifecycle operation is in progress")
        async with self._op_lock:
            self._reject_if_closing()
            if self._sm.state is not RunState.RUNNING:
                raise NotRunningError("the server is not running")
            await self._cancel_recovery()
            await self._stop_locked(operator=True)

    async def _stop_locked(self, *, operator: bool) -> None:
        run = self._run
        if run is None or self._sm.state is not RunState.RUNNING:
            raise NotRunningError("the server is not running")
        self._sm.transition(RunState.STOPPING)
        run.stop_requested = True
        if operator:
            self._persist_desired(running=False)
        await self._shutdown_process(run, graceful=True)
        await self._drain(run)
        self._run = None
        self._sm.transition(RunState.STOPPED)

    async def _shutdown_process(self, run: _Run, *, graceful: bool) -> None:
        """Bring the process down (design D7).

        Graceful: ``quit`` on stdin, wait ``shutdown_timeout``, then ``SIGTERM``, wait,
        then ``SIGKILL``. Forceful (a start that failed): skip the ``quit`` and its long
        wait and go straight to ``SIGTERM`` then ``SIGKILL``.
        """
        steps: list[tuple[float, signal.Signals | None]]
        if graceful:
            if run.proc.running:
                try:
                    await run.proc.write_line("quit")
                except Exception:
                    log.warning("could not write 'quit' to stdin; will wait then escalate")
            steps = [
                (self._settings.shutdown_timeout, None),
                (_TERM_GRACE, signal.SIGTERM),
                (_KILL_WAIT, signal.SIGKILL),
            ]
        else:
            steps = [(_TERM_GRACE, signal.SIGTERM), (_KILL_WAIT, signal.SIGKILL)]

        for timeout, sig in steps:
            if sig is not None and run.proc.running:
                log.warning("server still running; sending %s", sig.name)
                run.proc.send_signal(sig)
            try:
                await asyncio.wait_for(run.exited.wait(), timeout=timeout)
                return
            except TimeoutError:
                continue
        log.error("server pid=%s did not exit even after SIGKILL", run.proc.pid)

    async def _drain(self, run: _Run) -> None:
        for task in (run.pump, run.watcher):
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError, TimeoutError, Exception):
                    await asyncio.wait_for(asyncio.shield(task), timeout=_DRAIN_TIMEOUT)

    # -- lifecycle: restart --------------------------------------------------
    async def restart(self) -> None:
        self._reject_if_closing()
        if self.transition_in_progress():
            raise TransitionInProgressError("a lifecycle operation is in progress")
        async with self._op_lock:
            self._reject_if_closing()
            await self._cancel_recovery()
            if self._sm.state is RunState.RUNNING:
                self.console.add_marker("— restarting —")
                await self._stop_locked(operator=False)
            await self._start_locked(operator=True)

    # -- panel lifecycle coupling -------------------------------------------
    async def aclose(self) -> None:
        """Called when the panel itself is terminating: stop the child, leave no orphan.

        Intent is untouched, so a server that was running comes back on the next panel
        start and one the operator had stopped stays stopped.
        """
        self._closing = True
        self._closing_event.set()
        await self._cancel_recovery()
        async with self._op_lock:
            run = self._run
            if run is None:
                return
            if self._sm.state is RunState.RUNNING:
                await self._stop_locked(operator=False)
            elif run.proc.running:
                run.stop_requested = True
                await self._shutdown_process(run, graceful=True)
                await self._drain(run)
                self._run = None
                with contextlib.suppress(Exception):
                    self._sm.transition(RunState.STOPPED)

    async def restore(self) -> None:
        """Called on panel start: start the server if it was meant to be running."""
        if not self.desired_running():
            return
        if not self._installed():
            log.warning("the server was running before, but the game is not installed")
            return
        log.info("restoring the previously running server")
        try:
            await self.start()
        except SupervisorError as exc:
            log.error("restore failed: %s", exc)

    # -- intent persistence -------------------------------------------------
    def desired_running(self) -> bool:
        try:
            data = json.loads(self._settings.state_file.read_text())
            return bool(data["desired_running"])
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def _persist_desired(self, *, running: bool) -> None:
        path: Path = self._settings.state_file
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"desired_running": running}))
        tmp.replace(path)

    # -- commands -----------------------------------------------------------
    async def send_command(self, command: str) -> None:
        run = self._run
        if self._sm.state is not RunState.RUNNING or run is None:
            raise NotRunningError("the server is not running")
        await run.proc.write_line(command)
