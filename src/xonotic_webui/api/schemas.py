"""Response and request models; they define the OpenAPI schema the front end types from."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PlayerModel(BaseModel):
    id: int | None = Field(description="Event-log player id, when a join was observed.")
    ent: int = Field(description="The server's slot number for the client.")
    name: str = Field(description="Display name with Xonotic colour codes intact.")
    plain_name: str = Field(description="The name with colour codes removed.")
    bot: bool


class CrashModel(BaseModel):
    at: str = Field(description="ISO 8601 UTC time of the unexpected exit.")
    exit_code: int | None


class StartFailureModel(BaseModel):
    at: str
    reason: str
    exit_code: int | None


class StatusModel(BaseModel):
    state: Literal["stopped", "starting", "running", "stopping"]
    map: str | None
    gametype: str | None
    players: list[PlayerModel]
    human_count: int
    bot_count: int
    event_log: Literal["enabled", "unavailable"] | None = Field(
        description="Whether live player tracking from the event log is working."
    )
    last_crash: CrashModel | None
    restart_abandoned: bool
    last_start_failure: StartFailureModel | None


class ConsoleLineModel(BaseModel):
    seq: int
    kind: Literal["output", "command", "marker"]
    text: str = Field(description="The raw line, colour codes intact.")
    plain: str = Field(description="The line with colour codes removed.")


class CommandRequest(BaseModel):
    command: str = Field(description="A single console command line.")


class ApiError(BaseModel):
    code: str = Field(description="A stable machine-readable error code.")
    message: str = Field(description="A human-readable explanation.")


class ErrorResponse(BaseModel):
    detail: ApiError


class HealthModel(BaseModel):
    status: Literal["ok"]
    version: str
