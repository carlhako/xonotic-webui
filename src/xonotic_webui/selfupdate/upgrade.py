"""Requesting, following and reporting a panel upgrade (panel-self-update; design D3, D4).

The panel runs unprivileged and cannot replace itself. An upgrade is therefore a
*request*: the panel atomically writes ``<state_dir>/upgrade/request.json`` naming the
exact release tag it reported and a fresh request id. The root helper's systemd path unit
reacts to that file, installs that release, and restarts the panel. The panel learns the
outcome from the helper's ``<upgrade_status_dir>/status.json``, a root-owned file it can
only read. The helper echoes the request id in every status it writes; a status carrying
any other id (an earlier attempt, even at the same tag) is never this request's.

Durable files in the panel's state directory:

- ``upgrade_pending.json``: ``{from, to, tag, request_id, requested_at}`` while an upgrade
  is outstanding. It is authoritative for ``from``, and it survives the restart the helper
  causes, so the upgraded panel can report what happened.
- ``upgrade_last.json``: the most recent finished upgrade's outcome.

Unlike a backup-taking panel, nothing here stops the game server. The installer keeps the
old panel serving while it downloads and builds, and the panel's own shutdown quits the
game cleanly while keeping its running intent, which ``restore()`` honours on the next
start.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from xonotic_webui import __version__
from xonotic_webui.logging import get_logger
from xonotic_webui.selfupdate.files import read_json, write_json
from xonotic_webui.selfupdate.release_check import ReleaseChecker, now_iso
from xonotic_webui.settings import Settings
from xonotic_webui.supervisor import Supervisor

log = get_logger("selfupdate.upgrade")

TERMINAL = ("succeeded", "failed", "rejected")
POLL_SECONDS = 2.0
# After a restart, keep following a helper that still reports ``running`` for at least
# this long, even past ``upgrade_timeout_seconds``: the installer restarts the panel
# *before* the helper writes its final status.
FOLLOW_GRACE_SECONDS = 300.0


class UpgradeError(Exception):
    """An upgrade request that cannot go ahead. ``code`` is the API's 409 code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True)
class HelperStatus:
    request_id: str | None
    tag: str | None
    state: str | None  # running | succeeded | failed | rejected
    finished_at: str | None
    exit_code: int | None
    log_tail: str | None
    error: str | None


def manual_command(settings: Settings) -> str:
    """What an operator runs as root to upgrade without the helper."""
    return (
        f"curl -fsSL https://github.com/{settings.release_repo}"
        "/releases/latest/download/install.sh | bash"
    )


def _at_or_after(when: object, since: object) -> bool:
    """Whether ISO timestamp ``when`` is at or after ``since``; ``False`` if either does
    not parse."""
    try:
        return datetime.fromisoformat(str(when)) >= datetime.fromisoformat(str(since))
    except (TypeError, ValueError):
        return False


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


class UpgradeService:
    def __init__(
        self,
        settings: Settings,
        supervisor: Supervisor,
        release_check: ReleaseChecker,
        *,
        current: str = __version__,
        now: Callable[[], str] = now_iso,
        clock: Callable[[], float] | None = None,
        poll_seconds: float = POLL_SECONDS,
    ) -> None:
        self._settings = settings
        self._sup = supervisor
        self._release = release_check
        self.current = current
        self._now = now
        self._clock = clock
        self._poll = poll_seconds
        self._follow_task: asyncio.Task[None] | None = None

    # -- paths -----------------------------------------------------------
    @property
    def request_file(self) -> Path:
        return self._settings.upgrade_request_dir / "request.json"

    @property
    def processing_file(self) -> Path:
        return self._settings.upgrade_request_dir / "request.processing"

    @property
    def status_file(self) -> Path:
        return self._settings.upgrade_status_dir / "status.json"

    @property
    def pending_file(self) -> Path:
        return self._settings.state_dir / "upgrade_pending.json"

    @property
    def last_file(self) -> Path:
        return self._settings.state_dir / "upgrade_last.json"

    def _time(self) -> float:
        return self._clock() if self._clock is not None else asyncio.get_running_loop().time()

    # -- helper --------------------------------------------------------------
    def helper_installed(self) -> bool:
        return self._settings.upgrade_helper_path.is_file() and (
            self._settings.upgrade_status_dir.is_dir()
        )

    def manual_command(self) -> str | None:
        """The manual root command, or ``None`` when one-click upgrade is possible."""
        return None if self.helper_installed() else manual_command(self._settings)

    def helper_status(self) -> HelperStatus | None:
        data = read_json(self.status_file)
        if data is None:
            return None
        exit_code = data.get("exit_code")
        return HelperStatus(
            request_id=_str(data.get("request_id")),
            tag=_str(data.get("tag")),
            state=_str(data.get("state")),
            finished_at=_str(data.get("finished_at")),
            exit_code=exit_code if isinstance(exit_code, int) else None,
            log_tail=_str(data.get("log_tail")),
            error=_str(data.get("error")),
        )

    def _helper_status_for(self, request_id: object, requested_at: object) -> HelperStatus | None:
        """The helper's status if it concerns this request, matched by request id.

        A request the helper could not even read an id from is recorded as rejected with
        no id; it counts when it finished after this request was made."""
        st = self.helper_status()
        if st is None:
            return None
        if st.request_id is not None:
            return st if st.request_id == request_id else None
        if st.state == "rejected" and _at_or_after(st.finished_at, requested_at):
            return st
        return None

    # -- view ----------------------------------------------------------------
    def in_progress(self) -> bool:
        busy = self._follow_task is not None and not self._follow_task.done()
        return busy or self.pending_file.exists()

    def view(self) -> dict | None:
        """The in-flight upgrade, else the last finished one, else ``None``."""
        pending = read_json(self.pending_file)
        if pending is not None:
            st = self._helper_status_for(pending.get("request_id"), pending.get("requested_at"))
            # Any status for this request means the helper has taken it; a terminal one is
            # still "running" until the panel concludes it.
            return {
                "state": "running" if st is not None else "pending",
                "from": pending.get("from"),
                "to": pending.get("to"),
                "requested_at": pending.get("requested_at"),
                "finished_at": None,
                "error": None,
                "log_tail": None,
            }
        return read_json(self.last_file)

    # -- request -------------------------------------------------------------
    async def request(self, version: str) -> dict:
        """Validate and hand the upgrade to the helper.

        Returns once the request is written (the view is then ``pending``). Raises
        :class:`UpgradeError` for a refusal, having written nothing."""
        if self.in_progress():
            raise UpgradeError("upgrade_in_progress", "an upgrade is already pending or running")
        if not self.helper_installed():
            raise UpgradeError(
                "helper_not_installed",
                "the upgrade helper is not installed; run the installer as root to upgrade",
            )
        state = self._release.state
        if not self._release.update_available() or state.latest is None or state.tag is None:
            raise UpgradeError("no_update_available", "no newer panel release is known")
        if version.lstrip("v") != state.latest:
            raise UpgradeError(
                "version_mismatch",
                f"requested {version!r} but the available release is {state.latest!r}",
            )
        if self._sup.transition_in_progress():
            raise UpgradeError(
                "transition_in_progress",
                "the game server is starting or stopping; try again when it has finished",
            )

        request_id = uuid.uuid4().hex
        requested_at = self._now()
        write_json(
            self.pending_file,
            {
                "from": self.current,
                "to": state.latest,
                "tag": state.tag,
                "request_id": request_id,
                "requested_at": requested_at,
            },
        )
        try:
            write_json(self.request_file, {"tag": state.tag, "request_id": request_id})
        except OSError:
            self.pending_file.unlink(missing_ok=True)
            raise
        log.info("panel upgrade to %s requested; waiting for the helper", state.tag)
        self._start_follow()
        return self.view() or {}

    # -- following -------------------------------------------------------------
    def start(self) -> None:
        """On panel start: if an upgrade was outstanding, follow it to its end.

        The helper's installer restarts the panel *before* it writes the final status, so
        a fresh start routinely sees ``running`` and must keep polling rather than call
        the upgrade interrupted."""
        if self.pending_file.exists():
            self._start_follow()

    def _start_follow(self) -> None:
        if self._follow_task is None or self._follow_task.done():
            self._follow_task = asyncio.create_task(self._follow(), name="xonotic-upgrade-follow")

    async def _follow(self) -> None:
        pending = read_json(self.pending_file)
        if pending is None:
            self.pending_file.unlink(missing_ok=True)
            return
        request_id = pending.get("request_id")
        requested = pending.get("requested_at")
        try:
            elapsed = (datetime.now(UTC) - datetime.fromisoformat(requested)).total_seconds()
        except (TypeError, ValueError):
            elapsed = 0.0
        remaining = max(0.0, self._settings.upgrade_timeout_seconds - elapsed)
        started = self._time()
        deadline = started + remaining
        grace_deadline = started + FOLLOW_GRACE_SECONDS
        while True:
            st = self._helper_status_for(request_id, requested)
            if st is not None and st.state in TERMINAL:
                self._conclude(pending, st)
                return
            now = self._time()
            # A helper still reporting "running" is normally the installer finishing up
            # after restarting the panel: give it a grace period.
            helper_busy = st is not None and st.state == "running"
            if now >= deadline and not (helper_busy and now < grace_deadline):
                self._conclude(pending, st, interrupted=True)
                return
            await asyncio.sleep(self._poll)

    # -- outcome ---------------------------------------------------------------
    def _conclude(
        self, pending: dict, st: HelperStatus | None, *, interrupted: bool = False
    ) -> None:
        to = pending.get("to")
        if interrupted:
            state, error = "failed", "the upgrade was interrupted before it finished"
        elif st is not None and st.state == "succeeded":
            if to == self.current:
                state, error = "succeeded", None
            else:
                # Either the installer's rollback left the old panel running, or the old
                # panel is still up and the new code is not what is serving.
                state = "failed"
                error = f"the helper reported success but {self.current} is running, not {to}"
        else:
            state = st.state if st is not None and st.state else "failed"
            error = (st.error if st is not None else None) or f"the upgrade helper reported {state}"
        if state == "succeeded":
            log.info("panel upgraded %s -> %s", pending.get("from"), to)
        else:
            log.warning("panel upgrade to %s: %s", to, error)
        write_json(
            self.last_file,
            {
                "state": state,
                "from": pending.get("from"),
                "to": to,
                "requested_at": pending.get("requested_at"),
                "finished_at": self._now(),
                "error": error,
                "log_tail": st.log_tail if st is not None else None,
            },
        )
        self.pending_file.unlink(missing_ok=True)
        with contextlib.suppress(FileNotFoundError):
            self.request_file.unlink()

    async def stop(self) -> None:
        task = self._follow_task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
