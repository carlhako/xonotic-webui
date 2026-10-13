"""The bundled cvar catalogue (design D5)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from xonotic_webui.serversettings.catalogue import (
    CATALOGUE_RESOURCE,
    CvarCatalogue,
    build_from_cvarlist,
    dump_document,
    load_catalogue,
)

ROOT = Path(__file__).resolve().parent.parent
CVARLIST = ROOT / "tests" / "fixtures" / "xonotic" / "cvarlist.txt"
COMMITTED = ROOT / "src" / "xonotic_webui" / "serversettings" / CATALOGUE_RESOURCE


@pytest.fixture(scope="module")
def catalogue() -> CvarCatalogue:
    return load_catalogue()


def test_the_committed_catalogue_matches_the_script_output() -> None:
    spec = importlib.util.spec_from_file_location(
        "build_cvar_catalogue", ROOT / "scripts" / "build_cvar_catalogue.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert COMMITTED.read_text() == module.render()
    assert module.render() == dump_document(build_from_cvarlist(CVARLIST.read_text()))


def test_every_captured_cvar_is_in_the_catalogue(catalogue: CvarCatalogue) -> None:
    assert len(catalogue) == 6097  # the capture ends "6097 cvar(s)"
    assert catalogue.game_version == "0.8.6"


def test_entries_carry_default_and_description(catalogue: CvarCatalogue) -> None:
    entry = catalogue.get("HostName")
    assert entry is not None
    assert entry.name == "hostname"
    assert entry.default == "Xonotic 0.8.6 Server"
    assert "server browser" in entry.description
    assert entry.editable


def test_the_capture_values_are_not_taken_for_defaults(catalogue: CvarCatalogue) -> None:
    # The capture had settings applied (sv_autopause 0, timelimit 4); defaults are bracketed.
    assert catalogue.get("sv_autopause").default == "1"  # type: ignore[union-attr]
    assert catalogue.get("timelimit").default == "0"  # type: ignore[union-attr]


def test_reserved_and_secret_cvars_are_marked_not_editable(catalogue: CvarCatalogue) -> None:
    for name in ("sv_eventlog", "sv_eventlog_console", "sys_colortranslation", "port"):
        assert catalogue.get(name).editable is False  # type: ignore[union-attr]
    rcon = catalogue.get("rcon_password")
    assert rcon is not None and not rcon.editable
    assert rcon.default == ""  # the game masks the live value; the default is not secret


def test_the_catalogue_holds_no_value_the_capture_masked() -> None:
    assert "********" not in COMMITTED.read_text()


def test_search_by_name_ranks_prefix_matches_first(catalogue: CvarCatalogue) -> None:
    total, page = catalogue.search("maplist")
    names = [e.name for e in page]
    assert total >= 21
    assert any(part.startswith("maplist") for part in re.split(r"[_.]", names[0]))
    assert "g_maplist_votable" in [e.name for e in catalogue.search("maplist", 0, 100)[1]]


def test_search_matches_descriptions(catalogue: CvarCatalogue) -> None:
    names = [e.name for e in catalogue.search("map voting", 0, 100)[1]]
    assert "g_maplist_votable" in names  # only the description says "map voting"
    assert "g_maplist_votable" not in [e.name for e in catalogue.search("zzzznope")[1]]


def test_every_word_must_match(catalogue: CvarCatalogue) -> None:
    both = catalogue.search("maplist shuffle", 0, 100)[1]
    assert {e.name for e in both} >= {"g_maplist_shuffle"}
    assert all("shuffle" in f"{e.name} {e.description}".lower() for e in both)


def test_paging(catalogue: CvarCatalogue) -> None:
    total, first = catalogue.search("g_maplist", 0, 5)
    total2, second = catalogue.search("g_maplist", 5, 5)
    assert total == total2 and len(first) == 5
    assert not {e.name for e in first} & {e.name for e in second}
    assert catalogue.search("g_maplist", total + 10, 5)[1] == []
    assert catalogue.search("", 0, 3)[0] == len(catalogue)
