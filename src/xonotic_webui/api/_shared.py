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


def api_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def http_error_from_supervisor(exc: SupervisorError) -> HTTPException:
    status = _STATUS_BY_ERROR.get(type(exc), 409)
    return api_error(status, exc.code, str(exc))


def http_error_from_command(exc: Exception) -> HTTPException:
    if isinstance(exc, InvalidCommandError):
        return api_error(422, InvalidCommandError.code, str(exc))
    if isinstance(exc, SupervisorError):
        return http_error_from_supervisor(exc)
    raise exc


_KEEPALIVE_SECONDS = 15.0


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
        try:
            while True:
                if pending is None:
                    pending = asyncio.ensure_future(anext(events))
                done, _ = await asyncio.wait({pending}, timeout=_KEEPALIVE_SECONDS)
                if not done:
                    if await request.is_disconnected():
                        return
                    yield b": keepalive\n\n"
                    continue
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

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
