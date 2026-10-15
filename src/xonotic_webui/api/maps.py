"""Map routes: the catalogue, the gametype, the rotation and the match actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from starlette.requests import ClientDisconnect
from starlette.responses import FileResponse, Response

from xonotic_webui.api._shared import (
    LIFECYCLE_ERROR_RESPONSES,
    api_error,
    http_error_from_supervisor,
)
from xonotic_webui.api.schemas import (
    ErrorResponse,
    FavouritesModel,
    GametypeModel,
    GametypeRequest,
    GametypeResultModel,
    GametypesModel,
    GotoRequest,
    MapModel,
    MapsModel,
    MatchActionModel,
    PackageDuplicateModel,
    PackageInstalledModel,
    PackageRemovedModel,
    RotationItemModel,
    RotationModel,
    RotationRequest,
    RotationResultModel,
)
from xonotic_webui.maps.actions import MapActionError, MatchAction
from xonotic_webui.maps.control import RotationView
from xonotic_webui.maps.favourites import InvalidFavouriteError
from xonotic_webui.maps.packages import (
    AlreadyExistsError,
    PackageError,
    PackageNotFoundError,
    TooLargeError,
)
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


_PACKAGE_STATUS: dict[type[PackageError], int] = {
    TooLargeError: 413,
    AlreadyExistsError: 409,
    PackageNotFoundError: 404,
}
_PACKAGE_ERRORS = {
    404: {"model": ErrorResponse, "description": "There is no such package in the user directory."},
}


def _http_error(exc: Exception):
    if isinstance(exc, InvalidFavouriteError):
        return api_error(422, exc.code, str(exc), "map")
    if isinstance(exc, PackageError):
        return api_error(_PACKAGE_STATUS.get(type(exc), 422), exc.code, str(exc), "file")
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
                    package=m.package,
                    package_size=m.package_size,
                    pending_restart=m.pending_restart,
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

    # -- map packages ----------------------------------------------------------------------
    packages = runtime.package_store

    @router.put(
        "/packages/{filename:path}",
        response_model=PackageInstalledModel,
        responses={
            **_VALIDATION,
            409: {"model": ErrorResponse, "description": "A package of that name exists."},
            413: {"model": ErrorResponse, "description": "The package is over the size limit."},
        },
        summary="Install a map package; the request body is the raw .pk3 file",
    )
    async def put_package(filename: str, request: Request) -> PackageInstalledModel:
        declared: int | None
        try:
            declared = int(request.headers["content-length"])
        except (KeyError, ValueError):
            declared = None
        try:
            result = await packages.install(filename, request.stream(), declared_size=declared)
        except PackageError as exc:
            raise _http_error(exc) from exc
        except ClientDisconnect as exc:
            # Nothing was installed and nobody is left to read the answer.
            raise api_error(400, "upload_interrupted", "the upload was interrupted") from exc
        first = catalogue.get(result.maps[0])
        return PackageInstalledModel(
            name=result.name,
            size=result.size,
            maps=list(result.maps),
            duplicates=[
                PackageDuplicateModel(
                    map=d.map,
                    package=d.package,
                    source=d.source,  # type: ignore[arg-type]
                    used=d.used,
                )
                for d in result.duplicates
            ],
            restart_required=bool(first is not None and first.pending_restart),
        )

    @router.get(
        "/packages/{filename:path}",
        response_class=FileResponse,
        responses={
            200: {"content": {"application/octet-stream": {}}, "description": "The package."},
            **_PACKAGE_ERRORS,
        },
        summary="Download a map package from the user directory, byte for byte",
    )
    async def get_package(filename: str) -> FileResponse:
        try:
            path = packages.resolve(filename)
        except PackageError as exc:
            raise _http_error(exc) from exc
        return FileResponse(path, media_type="application/octet-stream", filename=path.name)

    @router.delete(
        "/packages/{filename:path}",
        response_model=PackageRemovedModel,
        responses=_PACKAGE_ERRORS,
        summary="Delete a map package from the user directory",
    )
    async def delete_package(filename: str) -> PackageRemovedModel:
        try:
            maps = packages.delete(filename)
        except PackageError as exc:
            raise _http_error(exc) from exc
        return PackageRemovedModel(name=filename, maps=list(maps))

    # -- favourites ------------------------------------------------------------------------
    favourites = runtime.favourites

    @router.get(
        "/favourites",
        response_model=FavouritesModel,
        summary="The favourite maps, shared by every browser",
    )
    async def get_favourites() -> FavouritesModel:
        return FavouritesModel(maps=favourites.maps())

    @router.put(
        "/favourites/{map_name}",
        response_model=FavouritesModel,
        responses={422: _VALIDATION[422]},
        summary="Star a map (idempotent); it need not be installed",
    )
    async def put_favourite(map_name: str) -> FavouritesModel:
        try:
            return FavouritesModel(maps=await favourites.add(map_name))
        except InvalidFavouriteError as exc:
            raise _http_error(exc) from exc

    @router.delete(
        "/favourites/{map_name}",
        response_model=FavouritesModel,
        responses={422: _VALIDATION[422]},
        summary="Unstar a map (idempotent)",
    )
    async def delete_favourite(map_name: str) -> FavouritesModel:
        try:
            return FavouritesModel(maps=await favourites.remove(map_name))
        except InvalidFavouriteError as exc:
            raise _http_error(exc) from exc

    return router
