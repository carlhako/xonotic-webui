"""Shared API helpers: structured errors and SSE plumbing."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import HTTPException, Request
from starlette.responses import StreamingResponse

from xonotic_webui.api.schemas import ErrorResponse
from xonotic_webui.console.console import InvalidCommandError
from xonotic_webui.supervisor import (
    AlreadyRunningError,
    NoInstallationError,
    NotRunningError,
    ReadinessTimeoutError,
    StartFailedError,
    SupervisorError,
    TransitionInProgressError,
)

# Lifecycle errors map to precise statuses (server-lifecycle: conflicting operations are
# rejected; web-ui-shell: the dashboard shows the error returned).
_STATUS_BY_ERROR: dict[type[SupervisorError], int] = {
    AlreadyRunningError: 409,
    NotRunningError: 409,
    TransitionInProgressError: 409,
    NoInstallationError: 503,  # a required component is missing from the host
    ReadinessTimeoutError: 504,  # the server did not answer in time
    StartFailedError: 502,  # the server process died while starting
}

LIFECYCLE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    409: {"model": ErrorResponse, "description": "Not valid in the current state."},
    502: {"model": ErrorResponse, "description": "The server exited while starting."},
    503: {"model": ErrorResponse, "description": "The game is not installed."},
    504: {"model": ErrorResponse, "description": "The server did not become ready in time."},
}


def api_error(status: int, code: str, message: str, field: str | None = None) -> HTTPException:
    detail: dict[str, Any] = {"code": code, "message": message}
    if field is not None:
        detail["field"] = field
    return HTTPException(status_code=status, detail=detail)


def http_error_from_supervisor(exc: SupervisorError) -> HTTPException:
    status = _STATUS_BY_ERROR.get(type(exc), 409)
    return api_error(status, exc.code, str(exc))


def http_error_from_command(exc: Exception) -> HTTPException:
    if isinstance(exc, InvalidCommandError):
        return api_error(422, InvalidCommandError.code, str(exc))
    if isinstance(exc, SupervisorError):
        return http_error_from_supervisor(exc)
    raise exc


class EventStreamResponse(StreamingResponse):
    """A server-sent-events response; its media type makes OpenAPI document the stream."""

    media_type = "text/event-stream"


_KEEPALIVE_SECONDS = 15.0
# How often an idle stream checks whether the panel is shutting down.
_POLL_SECONDS = 1.0

_shutting_down = False


def request_shutdown() -> None:
    """Tell every open event stream to finish.

    Called from the process's termination signal handler. uvicorn waits for open
    connections before running the lifespan shutdown (which stops the game server), and
    an SSE stream never ends on its own, so without this a connected browser would hold
    the stop open until uvicorn's timeout cancels it.
    """
    global _shutting_down
    _shutting_down = True


def is_shutting_down() -> bool:
    return _shutting_down


def sse_response(
    events: AsyncIterator[Any],
    request: Request,
    *,
    serialize: Callable[[Any], str] | None = None,
) -> StreamingResponse:
    """Stream ``events`` as server-sent events.

    A comment line is sent periodically so proxies and the browser keep the connection
    open, and ``events`` is always closed when the client goes away so its subscription
    is released deterministically.
    """
    dump = serialize or json.dumps

    async def body() -> AsyncIterator[bytes]:
        yield b": connected\n\n"  # prelude so proxies flush headers immediately
        pending: asyncio.Future[Any] | None = None
        idle = 0.0
        try:
            while not is_shutting_down():
                if pending is None:
                    pending = asyncio.ensure_future(anext(events))
                done, _ = await asyncio.wait({pending}, timeout=_POLL_SECONDS)
                if not done:
                    idle += _POLL_SECONDS
                    if idle >= _KEEPALIVE_SECONDS:
                        idle = 0.0
                        if await request.is_disconnected():
                            return
                        yield b": keepalive\n\n"
                    continue
                idle = 0.0
                task, pending = pending, None
                try:
                    event = task.result()
                except StopAsyncIteration:
                    return
                yield f"data: {dump(event)}\n\n".encode()
        except (ConnectionResetError, RuntimeError):
            return
        finally:
            if pending is not None:
                pending.cancel()
                with contextlib.suppress(BaseException):
                    await pending
            aclose = getattr(events, "aclose", None)
            if aclose is not None:
                with contextlib.suppress(Exception):
                    await aclose()

    return EventStreamResponse(
        body(),
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
