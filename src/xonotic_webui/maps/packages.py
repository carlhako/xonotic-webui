"""Installing, fetching and removing the map packages in the user data directory.

Only ``<userdir>/data`` is ever touched; the game's own tree is read-only to the panel.
An upload is validated completely before the game can see it (change
``add-map-packages-and-favourites``, design D3):

1. the file name is a plain ``.pk3`` name that can be used verbatim as the target;
2. the size is under :data:`MAX_PACKAGE_BYTES`, counted while streaming;
3. the body goes to ``.upload-<random>.part`` in the same directory, which neither the
   catalogue nor the game matches (both glob ``*.pk3``);
4. the temp file opens as a zip, has only safe member names and contains a map;
5. it is installed with ``os.link``, which fails if the name exists (a rename would
   silently replace), and the temp file is removed.

Whatever goes wrong, the temp file is removed, so a failed or interrupted upload leaves
nothing behind. Download and delete resolve a name to a regular file directly in the user
data directory and nothing else, so a game package or a path is simply "not found".
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import secrets
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from xonotic_webui.logging import get_logger

if TYPE_CHECKING:
    from xonotic_webui.maps.catalogue import MapCatalogue

log = get_logger("map-packages")

MAX_PACKAGE_BYTES = 256 * 1024 * 1024

EXTENSION = ".pk3"
# The target file name, used verbatim: no separator, space, leading dot or ``..``. The
# extension is lower-case because the catalogue's glob is case-sensitive.
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.pk3$")

_PART_PREFIX = ".upload-"
_PART_SUFFIX = ".part"


class PackageError(Exception):
    """A package operation was refused; ``code`` is the stable machine-readable reason."""

    code = "package_error"


class NotPk3Error(PackageError):
    code = "not_pk3"


class BadFilenameError(PackageError):
    code = "bad_filename"


class TooLargeError(PackageError):
    code = "too_large"


class NotAPackageError(PackageError):
    code = "not_a_package"


class NoMapError(PackageError):
    code = "no_map"


class AlreadyExistsError(PackageError):
    code = "already_exists"


class PackageNotFoundError(PackageError):
    code = "package_not_found"


@dataclass(frozen=True)
class Duplicate:
    """A map in the upload whose name another installed package already provides."""

    map: str
    package: str  # the other package's file name
    source: str  # "game" | "user"
    used: bool  # True when the uploaded map is the one the game will use


@dataclass(frozen=True)
class InstalledPackage:
    name: str
    size: int
    maps: tuple[str, ...]
    duplicates: tuple[Duplicate, ...]


def validate_upload_name(name: str) -> None:
    """Raise unless ``name`` is a name an upload may be installed under."""
    if not name.endswith(EXTENSION):
        raise NotPk3Error(
            "only .pk3 map packages are accepted (the extension must be lower-case .pk3)"
        )
    if NAME_PATTERN.fullmatch(name) is None:
        raise BadFilenameError(
            "the file name is not allowed: use letters, digits, '.', '_' and '-' only, "
            "starting with a letter or digit, at most 100 characters"
        )


def package_maps(path: Path) -> tuple[str, ...]:
    """The playable map names in a package (``maps/<name>.bsp``, not starting with ``_``).

    Raises :class:`NotAPackageError` for a file that is not a zip or has an unsafe member.
    """
    try:
        with zipfile.ZipFile(path) as zf:
            members = zf.namelist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise NotAPackageError("the file is not a valid map package (a zip archive)") from exc
    maps: list[str] = []
    for member in members:
        pure = PurePosixPath(member)
        if pure.is_absolute() or ".." in pure.parts or "\\" in member:
            raise NotAPackageError(f"the package has an unsafe member name: {member!r}")
        if len(pure.parts) == 2 and pure.parts[0] == "maps" and pure.suffix.lower() == ".bsp":
            if not pure.stem.startswith("_") and pure.stem not in maps:
                maps.append(pure.stem)
    return tuple(sorted(maps))


def _unlink_quietly(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()


class PackageStore:
    def __init__(
        self, user_data: Path, catalogue: MapCatalogue, *, max_bytes: int = MAX_PACKAGE_BYTES
    ) -> None:
        self._dir = user_data
        self._catalogue = catalogue
        self._max = max_bytes

    @property
    def max_bytes(self) -> int:
        return self._max

    # -- upload ------------------------------------------------------------------------
    async def install(
        self, name: str, body: AsyncIterator[bytes], *, declared_size: int | None = None
    ) -> InstalledPackage:
        """Validate and install an uploaded package; nothing is left behind on failure."""
        validate_upload_name(name)
        if declared_size is not None and declared_size > self._max:
            raise TooLargeError(self._too_large())
        final = self._dir / name
        if final.exists():  # an early answer; the link below is the atomic check
            raise AlreadyExistsError(f"{name} is already installed; delete it first")
        await asyncio.to_thread(self._dir.mkdir, parents=True, exist_ok=True)
        temp = self._dir / f"{_PART_PREFIX}{secrets.token_hex(8)}{_PART_SUFFIX}"
        try:
            size = await self._receive(temp, body)
            maps = await asyncio.to_thread(self._check, temp)
            duplicates = self._duplicates(name, maps)
            await asyncio.to_thread(self._link, temp, final, name)
        finally:
            _unlink_quietly(temp)
        log.info("installed map package %s (%d bytes, maps: %s)", name, size, ", ".join(maps))
        return InstalledPackage(name, size, maps, duplicates)

    async def _receive(self, temp: Path, body: AsyncIterator[bytes]) -> int:
        size = 0
        fh = await asyncio.to_thread(open, temp, "xb")
        try:
            async for chunk in body:
                size += len(chunk)
                if size > self._max:
                    raise TooLargeError(self._too_large())
                await asyncio.to_thread(fh.write, chunk)
        finally:
            await asyncio.shield(asyncio.to_thread(fh.close))
        return size

    def _too_large(self) -> str:
        return f"the package is larger than the {self._max // (1024 * 1024)} MB limit"

    @staticmethod
    def _check(temp: Path) -> tuple[str, ...]:
        maps = package_maps(temp)
        if not maps:
            raise NoMapError("the package contains no map (maps/<name>.bsp)")
        return maps

    def _duplicates(self, name: str, maps: tuple[str, ...]) -> tuple[Duplicate, ...]:
        found: list[Duplicate] = []
        for map_name in maps:
            existing = self._catalogue.get(map_name)
            if existing is None:
                continue
            # The user directory beats the game tree; among user packages the one whose
            # file name sorts later wins (the order the catalogue and the game use).
            used = existing.source == "game" or name > existing.package
            found.append(Duplicate(map_name, existing.package, existing.source, used))
        return tuple(found)

    @staticmethod
    def _link(temp: Path, final: Path, name: str) -> None:
        try:
            os.link(temp, final)
        except FileExistsError:
            raise AlreadyExistsError(f"{name} is already installed; delete it first") from None

    # -- download and delete -------------------------------------------------------------
    def resolve(self, name: str) -> Path:
        """The installed user package ``name``, or :class:`PackageNotFoundError`.

        The name must be a plain package name; the game tree is never searched.
        """
        if NAME_PATTERN.fullmatch(name) is not None:
            path = self._dir / name
            if path.is_file():
                return path
        raise PackageNotFoundError(f"there is no installed package {name!r} that can be changed")

    def delete(self, name: str) -> tuple[str, ...]:
        """Remove a user package; returns the maps that were in it."""
        path = self.resolve(name)
        try:
            maps = package_maps(path)
        except PackageError:
            maps = ()
        try:
            path.unlink()
        except FileNotFoundError:
            raise PackageNotFoundError(f"there is no installed package {name!r}") from None
        log.info("deleted map package %s", name)
        return maps

    # -- housekeeping --------------------------------------------------------------------
    def clean_stale_uploads(self) -> int:
        """Remove ``.upload-*.part`` files, which only a crash can leave; returns the count."""
        removed = 0
        try:
            leftovers = list(self._dir.glob(f"{_PART_PREFIX}*{_PART_SUFFIX}"))
        except OSError:
            return 0
        for path in leftovers:
            if path.is_file():
                _unlink_quietly(path)
                removed += 1
        if removed:
            log.warning("removed %d stale upload file(s) from %s", removed, self._dir)
        return removed
