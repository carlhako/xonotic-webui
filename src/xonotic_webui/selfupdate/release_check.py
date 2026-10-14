"""The panel's release check (panel-self-update spec; design D1).

One backend check shared by every client: ``GET {api}/repos/{repo}/releases/latest``
(which already excludes drafts and pre-releases), shortly after start and then
periodically. The last result is kept in memory and in ``release_check.json`` so
a restart while offline does not blank the header badge. A failed check never
discards the last good result; it only records ``check_error``.

Conditional requests (``If-None-Match``) keep the check cheap: a 304 does not
count against GitHub's unauthenticated rate limit. The persisted state carries a
``schema`` number; a file from an older schema keeps its result but not its ETag,
so the next check fetches the release in full and picks up fields (such as the
release notes) an older panel never stored.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import httpx

from xonotic_webui import __version__
from xonotic_webui.logging import get_logger
from xonotic_webui.selfupdate.files import atomic_write_text
from xonotic_webui.selfupdate.version import is_newer, parse_version
from xonotic_webui.settings import Settings

log = get_logger("selfupdate.release_check")

# Delay before the first check, so it never competes with the game server's start.
INITIAL_DELAY_SECONDS = 30.0
_TIMEOUT = httpx.Timeout(10.0)
# Bumped whenever the stored release gains fields that a 304 would never fill.
SCHEMA = 2


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class ReleaseCheckState:
    latest: str | None = None  # "0.5.0" (no leading v)
    tag: str | None = None  # "v0.5.0" exactly as published
    release_url: str | None = None
    name: str | None = None  # the release's title as published
    published_at: str | None = None
    notes: str | None = None  # Markdown body; None when published empty
    etag: str | None = None
    checked_at: str | None = None  # last attempt, successful or not
    check_error: str | None = None  # why the last attempt failed; None if it succeeded


class ReleaseChecker:
    def __init__(
        self,
        settings: Settings,
        *,
        current: str = __version__,
        transport: httpx.BaseTransport | None = None,
        now: Callable[[], str] = now_iso,
        initial_delay: float = INITIAL_DELAY_SECONDS,
    ) -> None:
        self._settings = settings
        self.current = current
        self._transport = transport
        self._now = now
        self._initial_delay = initial_delay
        self._path = settings.state_dir / "release_check.json"
        self._state = self._load()
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    # -- persistence ---------------------------------------------------
    def _load(self) -> ReleaseCheckState:
        try:
            raw = json.loads(self._path.read_text())
            fields = ReleaseCheckState.__dataclass_fields__
            state = ReleaseCheckState(**{k: v for k, v in raw.items() if k in fields})
            if raw.get("schema", 1) < SCHEMA:
                state.etag = None  # force a full fetch to fill the newer fields
            return state
        except FileNotFoundError:
            return ReleaseCheckState()
        except (OSError, ValueError, TypeError):
            log.warning("ignoring unreadable %s", self._path)
            return ReleaseCheckState()

    def _save(self) -> None:
        try:
            atomic_write_text(self._path, json.dumps({"schema": SCHEMA, **asdict(self._state)}))
        except OSError:
            log.exception("could not persist the release check result")

    # -- view ------------------------------------------------------------
    @property
    def state(self) -> ReleaseCheckState:
        return self._state

    def update_available(self) -> bool | None:
        """``True``/``False`` when known; ``None`` when there is no usable result."""
        if self._state.latest is None:
            return None
        return is_newer(self._state.latest, self.current)

    def view(self) -> dict:
        return {
            "current": self.current,
            "latest": self._state.latest,
            "update_available": bool(self.update_available()),
            "release_url": self._state.release_url,
            "release_name": self._state.name,
            "published_at": self._state.published_at,
            "notes": self._state.notes,
            "checked_at": self._state.checked_at,
            "check_error": self._state.check_error,
        }

    # -- the check -------------------------------------------------------
    def _fail(self, message: str) -> ReleaseCheckState:
        log.warning("release check failed: %s", message)
        self._state.checked_at = self._now()
        self._state.check_error = message
        self._save()
        return self._state

    def check_now(self) -> ReleaseCheckState:
        """Contact the release source once. Blocking; never raises."""
        url = (
            f"{self._settings.release_api_url.rstrip('/')}"
            f"/repos/{self._settings.release_repo}/releases/latest"
        )
        headers = {
            "User-Agent": self._settings.user_agent,
            "Accept": "application/vnd.github+json",
        }
        if self._state.etag and self._state.latest:
            headers["If-None-Match"] = self._state.etag
        try:
            with httpx.Client(
                headers=headers,
                timeout=_TIMEOUT,
                follow_redirects=True,
                transport=self._transport,
            ) as client:
                resp = client.get(url)
        except httpx.HTTPError as exc:
            return self._fail(f"release source unreachable: {exc}")

        if resp.status_code == 304:
            self._state.checked_at = self._now()
            self._state.check_error = None
            self._save()
            return self._state
        if resp.status_code in (403, 429):
            return self._fail(f"release source refused the request (HTTP {resp.status_code})")
        if resp.status_code == 404:
            return self._fail("no published release was found")
        if resp.status_code != 200:
            return self._fail(f"release source returned HTTP {resp.status_code}")

        try:
            payload = resp.json()
            tag = payload["tag_name"]
            html_url = payload["html_url"]
            unstable = bool(payload.get("draft")) or bool(payload.get("prerelease"))
            name = payload.get("name")
            published_at = payload.get("published_at")
            body = payload.get("body")
        except (ValueError, KeyError, TypeError) as exc:
            return self._fail(f"release source returned an unusable response: {exc}")
        if unstable:
            return self._fail(f"latest release {tag!r} is a draft or pre-release")
        parsed = parse_version(tag)
        if parsed is None:
            return self._fail(f"latest release tag {tag!r} is not a version")

        self._state = ReleaseCheckState(
            latest="{}.{}.{}".format(*parsed),
            tag=tag,
            release_url=html_url,
            name=name if isinstance(name, str) and name.strip() else None,
            published_at=published_at if isinstance(published_at, str) else None,
            notes=body.strip() if isinstance(body, str) and body.strip() else None,
            etag=resp.headers.get("ETag"),
            checked_at=self._now(),
            check_error=None,
        )
        self._save()
        if self.update_available():
            log.info("xonotic-webui %s is available (running %s)", self._state.latest, self.current)
        return self._state

    async def check(self) -> ReleaseCheckState:
        """Run one check off the event loop. Concurrent callers share one request."""
        if self._lock.locked():
            async with self._lock:
                return self._state
        async with self._lock:
            return await asyncio.to_thread(self.check_now)

    # -- periodic --------------------------------------------------------
    def start(self) -> None:
        if not self._settings.release_check_enabled:
            log.info("release check disabled (release_check_enabled=false)")
            return
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="xonotic-release-check")

    async def _loop(self) -> None:
        await asyncio.sleep(self._initial_delay)
        interval = self._settings.release_check_interval_hours * 3600.0
        while True:
            try:
                await self.check()
            except Exception:
                log.exception("release check raised unexpectedly")
            await asyncio.sleep(interval)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
