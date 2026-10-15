"""Response and request models; they define the OpenAPI schema the front end types from."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class MatchActionModel(BaseModel):
    id: int = Field(description="Increases with every action, so clients can tell them apart.")
    kind: Literal["goto", "skip", "restart"]
    map: str | None = Field(description="The requested map, for go to map.")
    state: Literal["pending", "done", "timed_out"] = Field(
        description="pending until the next match starts; timed_out if none did in time."
    )


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
    action: MatchActionModel | None = Field(
        description="The latest map action and whether it has completed."
    )


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
    field: str | None = Field(
        default=None, description="The setting or cvar the error is about, when there is one."
    )


class ErrorResponse(BaseModel):
    detail: ApiError


class HealthModel(BaseModel):
    status: Literal["ok"]
    version: str


# --- panel self-update -----------------------------------------------------------------


class PanelUpgrade(BaseModel):
    """An upgrade of the panel itself: in flight, or the last one that finished."""

    model_config = ConfigDict(populate_by_name=True)

    state: Literal["pending", "running", "succeeded", "failed", "rejected"] = Field(
        description=(
            "pending until the helper takes the request; running while it installs; then "
            "the outcome."
        )
    )
    from_version: str | None = Field(
        default=None, alias="from", description="The version that was running when requested."
    )
    to: str | None = Field(default=None, description="The version that was requested.")
    requested_at: str | None = None
    finished_at: str | None = None
    error: str | None = Field(default=None, description="Why it did not succeed.")
    log_tail: str | None = Field(
        default=None, description="The end of the installer's output, for a failure."
    )


class PanelVersion(BaseModel):
    current: str = Field(description="The version of the running panel.")
    latest: str | None = Field(description="The latest stable release; null if never checked.")
    update_available: bool
    release_url: str | None = Field(description="The latest release's page on GitHub.")
    release_name: str | None = Field(description="The latest release's title, as published.")
    published_at: str | None
    notes: str | None = Field(description="The latest release's notes (Markdown); null if none.")
    checked_at: str | None = Field(description="When the last check ran, successful or not.")
    check_error: str | None = Field(description="Why the last check failed, if it did.")
    one_click_available: bool = Field(description="Whether the upgrade helper is installed.")
    manual_command: str | None = Field(
        description="The command to run as root to upgrade; null when one-click is available."
    )
    upgrade: PanelUpgrade | None = Field(
        description="The upgrade in flight, else the last one that finished."
    )


class PanelUpgradeRequest(BaseModel):
    version: str = Field(description="The release to upgrade to; must be the one reported.")


# --- server settings -------------------------------------------------------------------

ApplyClassName = Literal["now", "next_map", "next_start", "may_need_restart"]
SettingValue = str | int | float | bool


class ChoiceModel(BaseModel):
    value: str
    label: str


class ValueLabelModel(BaseModel):
    value: int
    label: str


class SettingGroupModel(BaseModel):
    id: str
    label: str


class SwitchModel(BaseModel):
    label: str
    help: str
    off_value: int = Field(description="The setting's value while the switch is off.")
    enables: list[str] = Field(
        description="Settings that are only editable while the switch is on."
    )


class SettingModel(BaseModel):
    key: str = Field(description="The setting's id, which is the cvar it is written as.")
    group: str
    label: str
    help: str
    kind: Literal["string", "int", "float", "bool", "choice"]
    default: SettingValue
    value: SettingValue | None = Field(
        description="The value saved in the panel, or null when the default applies."
    )
    live_value: str | None = Field(
        description="What the running server currently has; null when stopped or unknown."
    )
    apply: ApplyClassName = Field(
        description="When a change to this setting takes effect on a running server."
    )
    min: float | None
    max: float | None
    max_length: int | None
    choices: list[ChoiceModel]
    unit: Literal["minutes", "score"] | None
    value_labels: list[ValueLabelModel] = Field(description="Names for special numeric values.")
    switch: SwitchModel | None = Field(
        description="An on/off switch for this setting, or null for an ordinary one."
    )
    server_cfg: bool = Field(description="server.cfg also sets this; the panel's value wins.")


class SettingsModel(BaseModel):
    running: bool
    groups: list[SettingGroupModel]
    settings: list[SettingModel]
    score_unit: str | None = Field(
        description="What a score limit counts for the current gametype (frags, captures...)."
    )


class SettingsResultModel(BaseModel):
    applied: dict[str, ApplyClassName] = Field(
        description="For each changed setting, when it takes effect."
    )


class OverrideModel(BaseModel):
    name: str
    value: str
    live_value: str | None
    server_cfg: bool


class OverridesModel(BaseModel):
    running: bool
    overrides: list[OverrideModel]


class OverrideRequest(BaseModel):
    value: str


class OverrideResultModel(BaseModel):
    name: str
    apply: ApplyClassName


class CvarModel(BaseModel):
    name: str
    default: str
    description: str
    editable: bool = Field(description="False for cvars the panel reserves.")
    live_value: str | None
    override: str | None = Field(description="The raw override saved for this cvar, if any.")
    server_cfg: bool


class CvarPageModel(BaseModel):
    running: bool
    total: int
    offset: int
    limit: int
    items: list[CvarModel]


# --- maps and match control -------------------------------------------------------------


class GametypeModel(BaseModel):
    id: str
    name: str
    score_unit: str = Field(description="What a score limit counts: frags, captures, ...")
    offered: bool = Field(description="At least one installed map supports it.")
    map_count: int


class GametypesModel(BaseModel):
    gametypes: list[GametypeModel]
    selected: str | None = Field(description="The gametype the operator saved, if any.")
    running: str | None = Field(description="What the current match is being played as.")
    effective: str | None = Field(description="What the next map is played as.")


class GametypeRequest(BaseModel):
    gametype: str


class GametypeResultModel(BaseModel):
    gametype: str
    apply: ApplyClassName


class MapModel(BaseModel):
    name: str
    title: str
    description: str
    author: str
    gametypes: list[str] = Field(description="Empty when the map has no map information.")
    has_mapinfo: bool
    preview: bool = Field(description="A preview image is available at /api/maps/{name}/preview.")
    source: Literal["game", "user"]
    package: str = Field(description="File name of the package the map comes from.")
    package_size: int = Field(description="Size of that package in bytes.")
    pending_restart: bool = Field(
        description=(
            "The package was added after the server started: the game has not loaded it, "
            "so the map cannot be gone to until the server is restarted."
        )
    )


class MapsModel(BaseModel):
    maps: list[MapModel]


class FavouritesModel(BaseModel):
    maps: list[str] = Field(
        description="Starred map names, sorted. A map that is not installed may be listed."
    )


class PackageDuplicateModel(BaseModel):
    map: str
    package: str = Field(description="File name of the other installed package.")
    source: Literal["game", "user"]
    used: bool = Field(description="The uploaded map is the one the game uses.")


class PackageInstalledModel(BaseModel):
    name: str
    size: int = Field(description="Bytes.")
    maps: list[str] = Field(description="The maps the package contains.")
    duplicates: list[PackageDuplicateModel] = Field(
        description="Maps in the upload whose name another installed package also provides."
    )
    restart_required: bool = Field(
        description=(
            "The server is running and has not loaded this package: restart it to use the maps."
        )
    )


class PackageRemovedModel(BaseModel):
    name: str
    maps: list[str] = Field(description="The maps that were in the package.")


class RotationItemModel(BaseModel):
    name: str
    title: str | None
    installed: bool
    supported: bool | None = Field(
        description="Whether it can be played in the gametype; null when none is known."
    )


class RotationModel(BaseModel):
    maps: list[RotationItemModel]
    shuffle: bool | None = Field(description="Null until chosen: the game's default applies.")
    gametype: str | None = Field(description="The gametype `supported` was judged against.")


class RotationRequest(BaseModel):
    maps: list[str] = Field(description="Ordered; empty means every map for the gametype.")
    shuffle: bool | None = None


class RotationResultModel(BaseModel):
    apply: ApplyClassName
    rotation: RotationModel


class GotoRequest(BaseModel):
    map: str


# --- players (player-stats) ---------------------------------------------------------


class PlayerRow(BaseModel):
    id: int
    name: str = Field(description="The most recently used name, colour codes intact.")
    plain_name: str = Field(description="The name with colour codes removed.")
    is_bot: bool
    frags: int
    deaths: int
    kd: float = Field(description="frags / max(deaths, 1).")
    suicides: int
    teamkills: int
    score: float
    wins: int
    matches: int = Field(description="Finished matches played.")
    time_playing: float = Field(description="Seconds alive in matches (from the match report).")
    time_on_server: float = Field(description="Seconds connected, spectating included.")
    accuracy: float | None = Field(description="Hits over shots, or null when nothing was fired.")
    first_seen: int = Field(description="UTC epoch seconds.")
    last_seen: int = Field(description="UTC epoch seconds.")


class PlayerList(BaseModel):
    revision: int = Field(description="Changes whenever recorded data changes.")
    total: int = Field(description="Players matching the filter, across all pages.")
    players: list[PlayerRow]


class PlayerAlias(BaseModel):
    name: str
    plain_name: str
    last_used: int


class PlayerWeapon(BaseModel):
    weapon: str
    frags: float
    hit: float
    fired: float
    cnt_hit: float
    cnt_fired: float
    accuracy: float | None


class PlayerAchievement(BaseModel):
    name: str
    count: int


class PlayerExtra(BaseModel):
    name: str
    value: float


class PlayerDetail(PlayerRow):
    aliases: list[PlayerAlias] = Field(description="Every name used, most recent first.")
    sessions: int = Field(description="How many visits are recorded.")
    key_prefix: str | None = Field(
        description="At most the first 8 characters of the key fingerprint, if there is one."
    )
    damage_dealt: float
    damage_taken: float
    avg_latency: float | None = Field(description="Average ping in milliseconds, if known.")
    weapons: list[PlayerWeapon]
    achievements: list[PlayerAchievement]
    extra: list[PlayerExtra] = Field(description="Gametype specific figures, summed.")
    has_match_stats: bool = Field(
        description="False when the player has never been in an end-of-match report."
    )
