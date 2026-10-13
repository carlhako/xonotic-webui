"""Map routes: the catalogue, the gametype, the rotation and the match actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter
from starlette.responses import Response

from xonotic_webui.api._shared import (
    LIFECYCLE_ERROR_RESPONSES,
    api_error,
    http_error_from_supervisor,
)
from xonotic_webui.api.schemas import (
    ErrorResponse,
    GametypeModel,
    GametypeRequest,
    GametypeResultModel,
    GametypesModel,
    GotoRequest,
    MapModel,
    MapsModel,
    MatchActionModel,
    RotationItemModel,
    RotationModel,
    RotationRequest,
    RotationResultModel,
)
from xonotic_webui.maps.actions import MapActionError, MatchAction
from xonotic_webui.maps.control import RotationView
from xonotic_webui.serversettings.service import SettingsError
from xonotic_webui.serversettings.store import SettingsStoreError
from xonotic_webui.supervisor import SupervisorError

if TYPE_CHECKING:
    from xonotic_webui.runtime import Runtime

_VALIDATION = {
    422: {"model": ErrorResponse, "description": "The request was rejected; nothing changed."},
    500: {"model": ErrorResponse, "description": "The saved settings file cannot be read."},
}
_ACTION_ERRORS = {
    **LIFECYCLE_ERROR_RESPONSES,
    422: {"model": ErrorResponse, "description": "The map is not installed or not playable."},
}


def _http_error(exc: Exception):
    if isinstance(exc, SettingsStoreError):
        return api_error(500, exc.code, str(exc))
    if isinstance(exc, SettingsError):
        return api_error(422, exc.code, str(exc), exc.field)
    if isinstance(exc, MapActionError):
        return api_error(422, exc.code, str(exc), "map")
    if isinstance(exc, SupervisorError):
        return http_error_from_supervisor(exc)
    raise exc


def _rotation_model(view: RotationView) -> RotationModel:
    return RotationModel(
        maps=[
            RotationItemModel(
                name=i.name, title=i.title, installed=i.installed, supported=i.supported
            )
            for i in view.maps
        ],
        shuffle=view.shuffle,
        gametype=view.gametype,
    )


def _action_model(action: MatchAction) -> MatchActionModel:
    return MatchActionModel(**action.to_dict())


def build_maps_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(tags=["maps"])
    catalogue = runtime.map_catalogue
    control = runtime.map_control
    actions = runtime.match_actions

    @router.get(
        "/gametypes",
        response_model=GametypesModel,
        responses={500: _VALIDATION[500]},
        summary="The gametypes, which of them the installed maps can play, and the selection",
    )
    async def get_gametypes() -> GametypesModel:
        try:
            view = control.gametypes()
        except SettingsStoreError as exc:
            raise _http_error(exc) from exc
        return GametypesModel(
            gametypes=[
                GametypeModel(
                    id=o.gametype.id,
                    name=o.gametype.name,
                    score_unit=o.gametype.score_unit,
                    offered=o.offered,
                    map_count=o.map_count,
                )
                for o in view.options
            ],
            selected=view.selected,
            running=view.running,
            effective=view.effective,
        )

    @router.put(
        "/gametype",
        response_model=GametypeResultModel,
        responses=_VALIDATION,
        summary="Select the gametype; it applies at the next map",
    )
    async def put_gametype(body: GametypeRequest) -> GametypeResultModel:
        try:
            apply = await control.select_gametype(body.gametype)
        except (SettingsError, SettingsStoreError) as exc:
            raise _http_error(exc) from exc
        return GametypeResultModel(gametype=body.gametype, apply=apply.value)  # type: ignore[arg-type]

    @router.get("/maps", response_model=MapsModel, summary="The installed maps")
    async def get_maps() -> MapsModel:
        return MapsModel(
            maps=[
                MapModel(
                    name=m.name,
                    title=m.title,
                    description=m.description,
                    author=m.author,
                    gametypes=list(m.gametypes),
                    has_mapinfo=m.has_mapinfo,
                    preview=m.preview,
                    source=m.source,  # type: ignore[arg-type]
                )
                for m in catalogue.maps()
            ]
        )

    @router.get(
        "/maps/{name}/preview",
        responses={
            200: {"content": {"image/jpeg": {}, "image/png": {}}, "description": "The image."},
            404: {"model": ErrorResponse, "description": "The map has no preview image."},
        },
        summary="A map's preview image",
    )
    async def get_preview(name: str) -> Response:
        found = catalogue.preview(name)
        if found is None:
            raise api_error(404, "no_preview", f"the map {name!r} has no preview image")
        content, media_type = found
        return Response(
            content=content, media_type=media_type, headers={"Cache-Control": "max-age=3600"}
        )

    @router.get(
        "/rotation",
        response_model=RotationModel,
        responses={500: _VALIDATION[500]},
        summary="The map rotation as saved",
    )
    async def get_rotation() -> RotationModel:
        try:
            return _rotation_model(control.rotation())
        except SettingsStoreError as exc:
            raise _http_error(exc) from exc

    @router.put(
        "/rotation",
        response_model=RotationResultModel,
        responses=_VALIDATION,
        summary="Set the map rotation and shuffle; it applies at the next map",
    )
    async def put_rotation(body: RotationRequest) -> RotationResultModel:
        try:
            apply = await control.set_rotation(body.maps, body.shuffle)
            view = control.rotation()
        except (SettingsError, SettingsStoreError) as exc:
            raise _http_error(exc) from exc
        return RotationResultModel(apply=apply.value, rotation=_rotation_model(view))  # type: ignore[arg-type]

    @router.post(
        "/match/goto",
        status_code=202,
        response_model=MatchActionModel,
        responses=_ACTION_ERRORS,
        summary="End the match with the scoreboard and go to a map, with no vote",
    )
    async def goto(body: GotoRequest) -> MatchActionModel:
        try:
            return _action_model(await actions.goto(body.map))
        except (MapActionError, SupervisorError) as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/match/skip",
        status_code=202,
        response_model=MatchActionModel,
        responses=_ACTION_ERRORS,
        summary="End the match early; the game then votes or rotates as usual",
    )
    async def skip() -> MatchActionModel:
        try:
            return _action_model(await actions.skip())
        except (MapActionError, SupervisorError) as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/match/restart",
        status_code=202,
        response_model=MatchActionModel,
        responses=_ACTION_ERRORS,
        summary="Restart the current match on the same map",
    )
    async def restart() -> MatchActionModel:
        try:
            return _action_model(await actions.restart())
        except (MapActionError, SupervisorError) as exc:
            raise _http_error(exc) from exc

    return router
