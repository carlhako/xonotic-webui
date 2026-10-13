"""The cvar catalogue: every cvar of the pinned game version with default and description.

It is generated at build time from the captured 0.8.6 ``cvarlist`` reply
(``tests/fixtures/xonotic/cvarlist.txt``, by ``scripts/build_cvar_catalogue.py``) and
shipped as ``cvars.json``. The game version is pinned, so it is valid, and it works while
the server is stopped. The panel never asks the running server for the full list: the
reply is 6,000 lines and would push the console history out of its buffer (design D5).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

from xonotic_webui.colors import strip_leading_codes
from xonotic_webui.serversettings.registry import NOT_EDITABLE

CATALOGUE_RESOURCE = "cvars.json"
GAME_VERSION = "0.8.6"

# ``name is "value" ["default"] description``; the value may itself contain quotes, so the
# value is everything up to the *first* ``" ["`` and the default up to the next ``"]``.
_LINE = re.compile(r'^(?P<name>\S+) is "(?P<value>.*?)" \["(?P<default>.*?)"\](?: (?P<desc>.*))?$')


@dataclass(frozen=True)
class CatalogueEntry:
    name: str
    default: str
    description: str
    editable: bool


def build_from_cvarlist(text: str) -> dict[str, Any]:
    """The catalogue document for the text of a ``cvarlist`` reply."""
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        match = _LINE.match(strip_leading_codes(raw))
        if match is None:
            continue  # the trailing "N cvar(s)" line and anything not a cvar
        name = match.group("name")
        if name in seen:
            continue
        seen.add(name)
        entry: dict[str, Any] = {
            "name": name,
            "default": match.group("default"),
            "description": (match.group("desc") or "").strip(),
        }
        if name.lower() in NOT_EDITABLE:
            entry["editable"] = False
        entries.append(entry)
    entries.sort(key=lambda e: e["name"])
    return {"game_version": GAME_VERSION, "cvars": entries}


def dump_document(document: dict[str, Any]) -> str:
    return json.dumps(document, separators=(",", ":"), ensure_ascii=False) + "\n"


class CvarCatalogue:
    def __init__(self, document: dict[str, Any]) -> None:
        self.game_version: str = document["game_version"]
        self._entries = [
            CatalogueEntry(
                name=e["name"],
                default=e["default"],
                description=e["description"],
                editable=e.get("editable", True),
            )
            for e in document["cvars"]
        ]
        self._by_name = {e.name.lower(): e for e in self._entries}

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, name: str) -> CatalogueEntry | None:
        return self._by_name.get(name.lower())

    def search(
        self, query: str, offset: int = 0, limit: int = 50
    ) -> tuple[int, list[CatalogueEntry]]:
        """Entries whose name or description contains every word of ``query``.

        Ordered by how well the name matches (exact, prefix, a word of the name, anywhere
        in the name), then description-only matches; alphabetical within each. Returns the
        total match count and the requested page.
        """
        words = [w for w in query.lower().split() if w]
        if not words:
            matches = self._entries
        else:
            ranked: list[tuple[int, str, CatalogueEntry]] = []
            for entry in self._entries:
                name = entry.name.lower()
                if not all(w in f"{name} {entry.description.lower()}" for w in words):
                    continue
                ranked.append((_rank(name, words), name, entry))
            ranked.sort(key=lambda t: (t[0], t[1]))
            matches = [entry for _, _, entry in ranked]
        offset = max(0, offset)
        return len(matches), matches[offset : offset + max(0, limit)]


def _rank(name: str, words: list[str]) -> int:
    if not all(w in name for w in words):
        return 4  # only the description matched
    if name == " ".join(words):
        return 0
    if name.startswith(words[0]):
        return 1
    parts = re.split(r"[_.]", name)
    if all(any(part.startswith(w) for part in parts) for w in words):
        return 2
    return 3


@lru_cache(maxsize=1)
def load_catalogue() -> CvarCatalogue:
    text = resources.files("xonotic_webui.serversettings").joinpath(CATALOGUE_RESOURCE).read_text()
    return CvarCatalogue(json.loads(text))
