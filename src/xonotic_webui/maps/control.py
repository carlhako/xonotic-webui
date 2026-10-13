"""Gametype selection and the map rotation (design D7, D8).

Both are stored in ``settings.json`` and written into the generated config, so they hold
across restarts. Running servers also get them as console lines. The game's working copy
of ``g_maplist`` is never shown: it shuffles it and fills it in when empty.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from xonotic_webui.maps.catalogue import MapCatalogue, MapEntry
from xonotic_webui.serversettings.registry import (
    GAMETYPES,
    GAMETYPES_BY_ID,
    ApplyClass,
    Gametype,
)
from xonotic_webui.serversettings.serialize import assignment
from xonotic_webui.serversettings.service import ServerSettingsService, SettingsError
from xonotic_webui.serversettings.store import (
    SettingsStoreError,
    StoreData,
    rotation_for_config,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class UnknownGametypeError(SettingsError):
    code = "unknown_gametype"


class GametypeUnavailableError(SettingsError):
    code = "gametype_unavailable"


class MapNotInstalledError(SettingsError):
    code = "map_not_installed"


@dataclass(frozen=True)
class GametypeOption:
    gametype: Gametype
    offered: bool  # at least one installed map supports it
    map_count: int


@dataclass(frozen=True)
class GametypeView:
    options: list[GametypeOption]
    selected: str | None  # the operator's saved choice
    running: str | None  # what the live match is being played as
    effective: str | None  # what the next map will be: selected, else running


@dataclass(frozen=True)
class RotationItem:
    name: str
    title: str | None  # None when the map is not installed (any more)
    installed: bool
    supported: bool | None  # None when no gametype is known to judge by


@dataclass(frozen=True)
class RotationView:
    maps: list[RotationItem]
    shuffle: bool | None
    gametype: str | None  # the gametype ``supported`` was judged against


class MapControl:
    def __init__(
        self,
        service: ServerSettingsService,
        catalogue: MapCatalogue,
        running_gametype: Callable[[], str | None],
    ) -> None:
        self._service = service
        self._catalogue = catalogue
        self._running_gametype = running_gametype

    @property
    def catalogue(self) -> MapCatalogue:
        return self._catalogue

    # -- gametype --------------------------------------------------------------------
    def effective_gametype(self) -> str | None:
        """The gametype the next map is played as: the saved choice, else the running one."""
        try:
            selected = self._service.load().gametype
        except SettingsStoreError:
            selected = None
        return selected or self._running_gametype()

    def gametypes(self) -> GametypeView:
        counts: dict[str, int] = {}
        for entry in self._catalogue.maps():
            for gametype in entry.gametypes:
                counts[gametype] = counts.get(gametype, 0) + 1
        selected = self._service.load().gametype
        running = self._running_gametype()
        return GametypeView(
            options=[
                GametypeOption(g, offered=counts.get(g.id, 0) > 0, map_count=counts.get(g.id, 0))
                for g in GAMETYPES
            ],
            selected=selected,
            running=running,
            effective=selected or running,
        )

    async def select_gametype(self, gametype: str) -> ApplyClass:
        """Persist ``gametype`` and queue it for the next map.

        The running match carries on; going to a map "now" is a separate action.
        """
        if gametype not in GAMETYPES_BY_ID:
            raise UnknownGametypeError(f"unknown gametype {gametype!r}", field="gametype")
        if gametype not in self._catalogue.gametypes_available():
            raise GametypeUnavailableError(
                f"no installed map supports {GAMETYPES_BY_ID[gametype].name}", field="gametype"
            )

        def mutate(data: StoreData) -> None:
            data.gametype = gametype

        await self._service.update(mutate)
        # The command is not allowed in a config file, so the generated cvars carry it at
        # the next start; the running server is told with the command itself.
        delivered = await self._service.send_live([f"gametype {gametype}"])
        return ApplyClass.NEXT_MAP if delivered else ApplyClass.NEXT_START

    # -- rotation ----------------------------------------------------------------------
    def rotation(self) -> RotationView:
        data = self._service.load()
        gametype = data.gametype or self._running_gametype()
        items: list[RotationItem] = []
        for name in data.rotation.maps:
            entry: MapEntry | None = self._catalogue.get(name)
            items.append(
                RotationItem(
                    name=name,
                    title=entry.title if entry else None,
                    installed=entry is not None,
                    supported=(entry.supports(gametype) if entry and gametype else None),
                )
            )
        return RotationView(maps=items, shuffle=data.rotation.shuffle, gametype=gametype)

    async def set_rotation(self, maps: list[str], shuffle: bool | None) -> ApplyClass:
        """Store the ordered rotation and shuffle flag (an empty list means all maps)."""
        cleaned: list[str] = []
        for name in maps:
            if self._catalogue.get(name) is None:
                raise MapNotInstalledError(f"map {name!r} is not installed", field="maps")
            if name not in cleaned:
                cleaned.append(name)

        def mutate(data: StoreData) -> None:
            data.rotation.maps = cleaned
            data.rotation.shuffle = shuffle

        data = await self._service.update(mutate)
        written = rotation_for_config(data, self._catalogue.gametype_map())
        commands = [assignment("g_maplist", " ".join(written))]
        if shuffle is not None:
            commands.append(f"g_maplist_shuffle {1 if shuffle else 0}")
        delivered = await self._service.send_live(commands)
        return ApplyClass.NEXT_MAP if delivered else ApplyClass.NEXT_START
