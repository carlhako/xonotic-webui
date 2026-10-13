"""The panel's settings store and the config generated from it (design D1).

``STATE_DIR/settings.json`` is the source of truth. From it the panel generates
``userdir/data/<APP_NAME>-settings.cfg``, which the wrapper config runs after the
operator's ``server.cfg`` and before the cvars the panel forces.

The generated file lists, in this order: the saved curated settings, the gametype
selection, the rotation, then the raw overrides (which therefore win over a curated
setting of the same cvar).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xonotic_webui.serversettings.registry import (
    CURATED,
    CURATED_BY_KEY,
    GAMETYPES,
    GAMETYPES_BY_ID,
)
from xonotic_webui.serversettings.serialize import assignment

_STORE_VERSION = 1

CONFIG_HEADER = (
    "// Managed by xonotic-webui: generated from the panel's settings on every save and\n"
    "// every start, do not edit. Runs after server.cfg, before the cvars the panel forces.\n"
)


class SettingsStoreError(RuntimeError):
    """``settings.json`` exists but cannot be understood. The file is left untouched."""

    code = "settings_unreadable"


@dataclass
class Rotation:
    maps: list[str] = field(default_factory=list)
    # ``None`` until the operator chooses, so the game's own default applies.
    shuffle: bool | None = None


@dataclass
class StoreData:
    values: dict[str, Any] = field(default_factory=dict)
    overrides: dict[str, str] = field(default_factory=dict)
    gametype: str | None = None
    rotation: Rotation = field(default_factory=Rotation)

    def copy(self) -> StoreData:
        return StoreData(
            values=dict(self.values),
            overrides=dict(self.overrides),
            gametype=self.gametype,
            rotation=Rotation(list(self.rotation.maps), self.rotation.shuffle),
        )


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> StoreData:
        """The stored data; an absent file is an empty store."""
        try:
            raw = self.path.read_text()
        except FileNotFoundError:
            return StoreData()
        except OSError as exc:
            raise SettingsStoreError(f"cannot read {self.path}: {exc}") from exc
        try:
            doc = json.loads(raw)
            return _from_document(doc)
        except (ValueError, TypeError, KeyError) as exc:
            raise SettingsStoreError(
                f"{self.path} is not a valid settings file ({exc}); fix or remove it"
            ) from exc

    def save(self, data: StoreData) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        document = {
            "version": _STORE_VERSION,
            "values": data.values,
            "overrides": data.overrides,
            "gametype": data.gametype,
            "rotation": {"maps": data.rotation.maps, "shuffle": data.rotation.shuffle},
        }
        with tmp.open("w") as fh:
            json.dump(document, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(self.path)


def _from_document(doc: Any) -> StoreData:
    if not isinstance(doc, dict):
        raise TypeError("the top level must be an object")
    values = doc.get("values", {})
    overrides = doc.get("overrides", {})
    rotation = doc.get("rotation", {}) or {}
    gametype = doc.get("gametype")
    if not isinstance(values, dict) or not isinstance(overrides, dict):
        raise TypeError("values and overrides must be objects")
    if not isinstance(rotation, dict):
        raise TypeError("rotation must be an object")
    maps = rotation.get("maps", [])
    shuffle = rotation.get("shuffle")
    if not isinstance(maps, list) or not all(isinstance(m, str) for m in maps):
        raise TypeError("rotation.maps must be a list of names")
    if shuffle is not None and not isinstance(shuffle, bool):
        raise TypeError("rotation.shuffle must be true, false or null")
    if gametype is not None and not isinstance(gametype, str):
        raise TypeError("gametype must be text or null")
    if not all(isinstance(v, str) for v in overrides.values()):
        raise TypeError("override values must be text")
    return StoreData(
        values=dict(values),
        overrides=dict(overrides),
        gametype=gametype,
        rotation=Rotation(list(maps), shuffle),
    )


def rotation_for_config(
    data: StoreData, map_gametypes: Mapping[str, frozenset[str]] | None
) -> list[str]:
    """The stored rotation without the maps that cannot be played in the gametype.

    With no gametype selected, or no catalogue, nothing can be judged and the list is
    used as stored (the game itself skips what it cannot play).
    """
    maps = data.rotation.maps
    if data.gametype is None or map_gametypes is None:
        return list(maps)
    return [m for m in maps if data.gametype in map_gametypes.get(m, frozenset())]


def render_settings_cfg(
    data: StoreData, map_gametypes: Mapping[str, frozenset[str]] | None = None
) -> str:
    """The generated config text. An empty store gives the header only."""
    lines: list[str] = [CONFIG_HEADER.rstrip("\n")]

    for setting in CURATED:
        if setting.key in data.values:
            lines.append(assignment(setting.key, setting.wire(data.values[setting.key])))

    if data.gametype is not None:
        lines.append("// gametype")
        for gametype in GAMETYPES:
            lines.append(f"{gametype.cvar} {1 if gametype.id == data.gametype else 0}")

    rotation = rotation_for_config(data, map_gametypes)
    if rotation:
        lines.append("// rotation")
        lines.append(assignment("g_maplist", " ".join(rotation)))
    if data.rotation.shuffle is not None:
        lines.append(f"g_maplist_shuffle {1 if data.rotation.shuffle else 0}")

    if data.overrides:
        lines.append("// raw overrides")
        for name in sorted(data.overrides):
            lines.append(assignment(name, data.overrides[name], create=True))

    return "\n".join(lines) + "\n"


def known_gametype(gametype: str) -> bool:
    return gametype in GAMETYPES_BY_ID


def known_setting(key: str) -> bool:
    return key in CURATED_BY_KEY
