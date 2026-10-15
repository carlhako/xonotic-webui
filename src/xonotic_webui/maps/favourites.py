"""The favourite maps: a small panel-owned file shared by every client (design D6).

``<state>/favourites.json`` is ``{"maps": ["boil", ...]}``. It is deliberately not part of
the server settings store, which feeds the generated game config. Names are kept even when
the map is not installed, so a package that is removed and installed again comes back
starred. The data is cosmetic: a missing file is empty, and an unreadable one is treated as
empty with a warning instead of blocking the Maps page.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from xonotic_webui.logging import get_logger
from xonotic_webui.serversettings.serialize import validate_name

log = get_logger("favourites")

_VERSION = 1


class InvalidFavouriteError(ValueError):
    code = "invalid_map_name"


class FavouritesStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        # Read-modify-write is one critical section, so concurrent adds all survive.
        self._lock = asyncio.Lock()

    # -- file ------------------------------------------------------------------------------
    def _read(self) -> list[str]:
        try:
            raw = json.loads(self._path.read_text())
            maps = raw["maps"]
            if not isinstance(maps, list) or not all(isinstance(m, str) for m in maps):
                raise ValueError("maps is not a list of names")
        except FileNotFoundError:
            return []
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("ignoring unreadable favourites file %s: %s", self._path, exc)
            return []
        return sorted(set(maps))

    def _write(self, maps: list[str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        with tmp.open("w") as fh:
            json.dump({"version": _VERSION, "maps": maps}, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(self._path)

    # -- queries and changes ---------------------------------------------------------------
    def maps(self) -> list[str]:
        return self._read()

    @staticmethod
    def _checked(name: str) -> str:
        try:
            return validate_name(name)
        except ValueError as exc:
            raise InvalidFavouriteError(f"{name!r} is not a valid map name") from exc

    async def add(self, name: str) -> list[str]:
        """Idempotent add; returns the favourites afterwards."""
        self._checked(name)
        async with self._lock:
            maps = self._read()
            if name not in maps:
                maps = sorted({*maps, name})
                await asyncio.to_thread(self._write, maps)
            return maps

    async def remove(self, name: str) -> list[str]:
        """Idempotent remove; returns the favourites afterwards."""
        self._checked(name)
        async with self._lock:
            maps = self._read()
            if name in maps:
                maps = [m for m in maps if m != name]
                await asyncio.to_thread(self._write, maps)
            return maps
