"""Server-settings routes: curated settings, raw overrides and the cvar catalogue."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Body, Query

from xonotic_webui.api._shared import api_error
from xonotic_webui.api.schemas import (
    CvarModel,
    CvarPageModel,
    ErrorResponse,
    OverrideModel,
    OverrideRequest,
    OverrideResultModel,
    OverridesModel,
    SettingGroupModel,
    SettingModel,
    SettingsModel,
    SettingsResultModel,
    SettingValue,
)
from xonotic_webui.serversettings.registry import GAMETYPES_BY_ID, GROUPS
from xonotic_webui.serversettings.service import (
    ReservedCvarError,
    SettingsError,
    SettingState,
)
from xonotic_webui.serversettings.store import SettingsStoreError

if TYPE_CHECKING:
    from xonotic_webui.runtime import Runtime

_ERRORS = {
    422: {"model": ErrorResponse, "description": "The value or name was rejected; nothing saved."},
    500: {"model": ErrorResponse, "description": "The saved settings file cannot be read."},
}


def _http_error(exc: Exception):
    if isinstance(exc, SettingsStoreError):
        return api_error(500, exc.code, str(exc))
    if isinstance(exc, SettingsError):
        return api_error(422, exc.code, str(exc), exc.field)
    if isinstance(exc, ValueError) and hasattr(exc, "code"):
        return api_error(422, exc.code, str(exc))
    raise exc


def _setting_model(state: SettingState) -> SettingModel:
    s = state.setting
    return SettingModel(
        key=s.key,
        group=s.group,
        label=s.label,
        help=s.help,
        kind=s.kind,
        default=s.default,
        value=state.value,
        live_value=state.live_value,
        apply=s.apply.value,
        min=s.min,
        max=s.max,
        max_length=s.max_length,
        choices=[{"value": c.value, "label": c.label} for c in s.choices],  # type: ignore[misc]
        unit=s.unit,
        value_labels=[{"value": v, "label": label} for v, label in s.value_labels],  # type: ignore[misc]
        switch=(
            {  # type: ignore[arg-type]
                "label": s.switch.label,
                "help": s.switch.help,
                "off_value": s.switch.off_value,
                "enables": list(s.switch.enables),
            }
            if s.switch
            else None
        ),
        server_cfg=state.server_cfg,
    )


def build_settings_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(tags=["settings"])
    service = runtime.server_settings

    @router.get(
        "/settings",
        response_model=SettingsModel,
        responses={500: _ERRORS[500]},
        summary="The curated settings with their saved, default and live values",
    )
    async def get_settings() -> SettingsModel:
        try:
            states = await service.view()
        except SettingsStoreError as exc:
            raise _http_error(exc) from exc
        gametype = GAMETYPES_BY_ID.get(runtime.effective_gametype() or "")
        return SettingsModel(
            running=service.running,
            groups=[SettingGroupModel(id=g, label=label) for g, label in GROUPS],
            settings=[_setting_model(s) for s in states],
            score_unit=gametype.score_unit if gametype else None,
        )

    @router.patch(
        "/settings",
        response_model=SettingsResultModel,
        responses=_ERRORS,
        summary="Save settings; null resets one to its default",
    )
    async def patch_settings(
        changes: Annotated[dict[str, SettingValue | None], Body()],
    ) -> SettingsResultModel:
        try:
            applied = await service.patch(changes)
        except (SettingsError, SettingsStoreError) as exc:
            raise _http_error(exc) from exc
        return SettingsResultModel(applied={k: v.value for k, v in applied.items()})  # type: ignore[misc]

    @router.get(
        "/settings/overrides",
        response_model=OverridesModel,
        responses={500: _ERRORS[500]},
        summary="The raw cvar overrides",
    )
    async def get_overrides() -> OverridesModel:
        try:
            items = await service.overrides()
        except SettingsStoreError as exc:
            raise _http_error(exc) from exc
        return OverridesModel(
            running=service.running,
            overrides=[
                OverrideModel(
                    name=o.name, value=o.value, live_value=o.live_value, server_cfg=o.server_cfg
                )
                for o in items
            ],
        )

    @router.put(
        "/settings/overrides/{name}",
        response_model=OverrideResultModel,
        responses=_ERRORS,
        summary="Add or change a raw cvar override",
    )
    async def put_override(name: str, body: OverrideRequest) -> OverrideResultModel:
        try:
            apply = await service.put_override(name, body.value)
        except (SettingsError, SettingsStoreError) as exc:
            raise _http_error(exc) from exc
        return OverrideResultModel(name=name, apply=apply.value)  # type: ignore[arg-type]

    @router.delete(
        "/settings/overrides/{name}",
        response_model=OverrideResultModel,
        responses=_ERRORS,
        summary="Remove a raw cvar override",
    )
    async def delete_override(name: str) -> OverrideResultModel:
        try:
            apply = await service.delete_override(name)
        except (SettingsError, SettingsStoreError) as exc:
            raise _http_error(exc) from exc
        return OverrideResultModel(name=name, apply=apply.value)  # type: ignore[arg-type]

    @router.get(
        "/cvars",
        response_model=CvarPageModel,
        responses={500: _ERRORS[500]},
        summary="Search the game's cvars by name or description",
    )
    async def search_cvars(
        q: Annotated[str, Query(max_length=200)] = "",
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> CvarPageModel:
        try:
            page = await service.search_cvars(q, offset, limit)
        except SettingsStoreError as exc:
            raise _http_error(exc) from exc
        return CvarPageModel(
            running=service.running,
            total=page.total,
            offset=page.offset,
            limit=page.limit,
            items=[
                CvarModel(
                    name=c.entry.name,
                    default=c.entry.default,
                    description=c.entry.description,
                    editable=c.entry.editable,
                    live_value=c.live_value,
                    override=c.override,
                    server_cfg=c.server_cfg,
                )
                for c in page.items
            ],
        )

    return router


__all__ = ["ReservedCvarError", "build_settings_router"]
