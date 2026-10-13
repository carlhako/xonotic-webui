"""Console routes: the output stream (SSE) and command submission."""

from __future__ import annotations

from contextlib import aclosing
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

from xonotic_webui.api._shared import (
    EventStreamResponse,
    api_error,
    http_error_from_command,
    sse_response,
)
from xonotic_webui.api.schemas import CommandRequest, ConsoleLineModel, ErrorResponse
from xonotic_webui.console.buffer import ConsoleLine
from xonotic_webui.console.console import InvalidCommandError
from xonotic_webui.supervisor import SupervisorError

if TYPE_CHECKING:
    from xonotic_webui.runtime import Runtime


def _line_json(line: ConsoleLine) -> dict:
    return {"seq": line.seq, "kind": line.kind.value, "text": line.text, "plain": line.plain}


def build_console_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(prefix="/console", tags=["console"])

    @router.get(
        "/stream",
        response_class=EventStreamResponse,
        summary="Stream console output (server-sent events; each event is a ConsoleLine)",
        responses={
            200: {
                "model": ConsoleLineModel,
                "description": "An event stream; each event's data is a ConsoleLine.",
            }
        },
    )
    async def stream(request: Request):
        async def lines():
            async with aclosing(runtime.console.stream()) as source:
                async for line in source:
                    yield _line_json(line)

        return sse_response(lines(), request)

    @router.post(
        "/command",
        status_code=204,
        summary="Submit a single console command",
        responses={
            409: {"model": ErrorResponse, "description": "The server is not running."},
            422: {"model": ErrorResponse, "description": "Empty or multi-line command."},
        },
    )
    async def command(body: CommandRequest) -> None:
        try:
            await runtime.console.submit_command(body.command)
        except (InvalidCommandError, SupervisorError) as exc:
            raise http_error_from_command(exc) from exc

    return router


__all__ = ["api_error", "build_console_router"]
