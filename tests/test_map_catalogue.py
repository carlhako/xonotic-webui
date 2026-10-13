"""The installed-map catalogue (map-control spec)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.helpers import PREVIEW_BYTES, fake_maps, install_fake_maps, write_pk3
from xonotic_webui.maps.catalogue import MapCatalogue, parse_mapinfo


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    game = tmp_path / "game"
    userdir = tmp_path / "state" / "userdir"
    (game / "data").mkdir(parents=True)
    (userdir / "data").mkdir(parents=True)
    return game, userdir


def test_parse_mapinfo_reads_the_fields_that_matter() -> None:
    info = parse_mapinfo(
        """\
// a comment
title Stormkeep
description A castle // trailing comment
author Someone
gametype dm 20 5 5
gametype ctf 20 5 5
type tdm 20 5 5
cdtrack 3
size 100 100 100
"""
    )
    assert (info.title, info.description, info.author) == ("Stormkeep", "A castle", "Someone")
    assert info.gametypes == ("dm", "ctf", "tdm")
    assert not info.hidden
    assert parse_mapinfo("hidden\ngametype dm").hidden


def test_stock_maps_are_listed_with_title_gametypes_and_preview(
    roots: tuple[Path, Path],
) -> None:
    game, userdir = roots
    install_fake_maps(game)
    catalogue = MapCatalogue(game, userdir)
    maps = {m.name: m for m in catalogue.maps()}
    assert set(maps) == set(fake_maps())  # `_hudsetup` is internal and not listed
    stormkeep = maps["stormkeep"]
    assert stormkeep.title == "Stormkeep"
    assert stormkeep.gametypes == ("dm", "tdm")
    assert stormkeep.preview and stormkeep.has_mapinfo
    assert stormkeep.supports("tdm") and not stormkeep.supports("ctf")
    assert catalogue.preview("stormkeep") == (PREVIEW_BYTES, "image/jpeg")


def test_a_map_the_operator_adds_is_listed(roots: tuple[Path, Path]) -> None:
    game, userdir = roots
    install_fake_maps(game)
    catalogue = MapCatalogue(game, userdir)
    assert catalogue.get("mymap") is None
    write_pk3(
        userdir / "data" / "mymap.pk3",
        {"mymap": {"title": "My Map", "gametypes": ["ctf"], "preview": "png"}},
    )
    entry = catalogue.get("mymap")
    assert entry is not None
    assert (entry.title, entry.gametypes, entry.source) == ("My Map", ("ctf",), "user")
    assert catalogue.preview("mymap") == (PREVIEW_BYTES, "image/png")


def test_a_map_with_no_mapinfo_has_unknown_gametypes(roots: tuple[Path, Path]) -> None:
    game, userdir = roots
    write_pk3(game / "data" / "m.pk3", {"plain": {"mapinfo": False, "preview": None}})
    catalogue = MapCatalogue(game, userdir)
    entry = catalogue.get("plain")
    assert entry is not None
    assert entry.gametypes == ()
    assert not entry.has_mapinfo and not entry.preview
    assert entry.title == "plain"
    assert not any(entry.supports(g) for g in ("dm", "tdm", "ctf"))
    assert (
        "plain" not in catalogue.gametype_map() or catalogue.gametype_map()["plain"] == frozenset()
    )
    assert catalogue.gametypes_available() == set()
    assert catalogue.preview("plain") is None


def test_the_user_directory_shadows_the_game_tree(roots: tuple[Path, Path]) -> None:
    game, userdir = roots
    write_pk3(game / "data" / "a.pk3", {"boil": {"title": "Stock Boil", "gametypes": ["dm"]}})
    write_pk3(userdir / "data" / "b.pk3", {"boil": {"title": "My Boil", "gametypes": ["ctf"]}})
    entry = MapCatalogue(game, userdir).get("boil")
    assert entry is not None
    assert (entry.title, entry.gametypes, entry.source) == ("My Boil", ("ctf",), "user")


def test_a_shadowing_map_without_mapinfo_does_not_inherit_the_stock_one(
    roots: tuple[Path, Path],
) -> None:
    game, userdir = roots
    write_pk3(game / "data" / "a.pk3", {"boil": {"title": "Stock Boil", "gametypes": ["dm"]}})
    write_pk3(userdir / "data" / "b.pk3", {"boil": {"mapinfo": False, "preview": None}})
    entry = MapCatalogue(game, userdir).get("boil")
    assert entry is not None
    assert entry.gametypes == () and entry.source == "user"


def test_hidden_and_internal_maps_are_excluded(roots: tuple[Path, Path]) -> None:
    game, userdir = roots
    write_pk3(
        game / "data" / "a.pk3",
        {
            "secret": {"hidden": True},
            "_hudsetup": None,
            "_other": None,
            "shown": {"gametypes": ["dm"]},
        },
    )
    assert [m.name for m in MapCatalogue(game, userdir).maps()] == ["shown"]


def test_gametypes_offered_are_those_some_map_supports(roots: tuple[Path, Path]) -> None:
    game, userdir = roots
    write_pk3(
        game / "data" / "a.pk3",
        {"a": {"gametypes": ["dm", "tdm"]}, "b": {"gametypes": ["ctf"]}, "c": {"mapinfo": False}},
    )
    assert MapCatalogue(game, userdir).gametypes_available() == {"dm", "tdm", "ctf"}


def test_the_catalogue_is_cached_until_a_package_changes(
    roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    game, userdir = roots
    pk3 = write_pk3(game / "data" / "a.pk3", {"one": {"gametypes": ["dm"]}})
    catalogue = MapCatalogue(game, userdir)
    calls = []
    real_build = catalogue._build

    def counting(sources):  # type: ignore[no-untyped-def]
        calls.append(1)
        return real_build(sources)

    monkeypatch.setattr(catalogue, "_build", counting)
    assert [m.name for m in catalogue.maps()] == ["one"]
    catalogue.maps()
    catalogue.get("one")
    assert len(calls) == 1  # unchanged package: read once

    write_pk3(pk3, {"one": {"gametypes": ["dm"]}, "two": {"gametypes": ["dm"]}})
    os.utime(pk3, ns=(1, pk3.stat().st_mtime_ns + 10**9))
    assert [m.name for m in catalogue.maps()] == ["one", "two"]
    assert len(calls) == 2


def test_unreadable_packages_are_skipped(roots: tuple[Path, Path]) -> None:
    game, userdir = roots
    (game / "data" / "broken.pk3").write_bytes(b"not a zip")
    write_pk3(game / "data" / "ok.pk3", {"fine": {"gametypes": ["dm"]}})
    assert [m.name for m in MapCatalogue(game, userdir).maps()] == ["fine"]


def test_a_missing_data_directory_is_an_empty_catalogue(tmp_path: Path) -> None:
    assert MapCatalogue(tmp_path / "nogame", tmp_path / "nouser").maps() == []


# The real 0.8.6 server writes this for a map with no map information; the file below is
# what it wrote for a copy of boil.bsp (spike, config-and-maps task 4.2).
_GENERATED = """\
title Boil
description Stay calm and watch how your enemy is boiling with anger.
author kuniu the frogg, Mirio
cdtrack 1
has weapons
// uncomment this if you added turrets: has turrets
gametype dm // defaults: timelimit=15 pointlimit=30 leadlimit=0
gametype duel // defaults: timelimit=10 pointlimit=0 leadlimit=0
gametype mayhem // defaults: timelimit=15 pointlimit=1000 leadlimit=0
gametype surv // defaults: timelimit=20 pointlimit=12
// optional: hidden
"""


def test_a_map_the_game_generated_information_for_uses_it(roots: tuple[Path, Path]) -> None:
    game, userdir = roots
    write_pk3(userdir / "data" / "c.pk3", {"custom": {"mapinfo": False, "preview": None}})
    catalogue = MapCatalogue(game, userdir)
    assert catalogue.get("custom").gametypes == ()  # the server has not run yet

    generated = userdir / "data" / "data" / "maps" / "autogenerated"
    generated.mkdir(parents=True)
    (generated / "custom.mapinfo").write_text(_GENERATED)
    entry = catalogue.get("custom")  # picked up without touching a package
    assert entry is not None
    assert entry.gametypes == ("dm", "duel", "mayhem", "surv")
    assert entry.title == "Boil" and entry.has_mapinfo
    assert catalogue.gametypes_available() == {"dm", "duel", "mayhem", "surv"}


def test_a_map_that_ships_mapinfo_is_never_overridden_by_a_generated_file(
    roots: tuple[Path, Path],
) -> None:
    game, userdir = roots
    write_pk3(game / "data" / "a.pk3", {"boil": {"title": "Stock", "gametypes": ["ctf"]}})
    generated = userdir / "data" / "data" / "maps" / "autogenerated"
    generated.mkdir(parents=True)
    (generated / "boil.mapinfo").write_text(_GENERATED)
    entry = MapCatalogue(game, userdir).get("boil")
    assert entry is not None and entry.gametypes == ("ctf",)


def test_a_generated_file_without_a_map_is_ignored(roots: tuple[Path, Path]) -> None:
    game, userdir = roots
    generated = userdir / "data" / "data" / "maps" / "autogenerated"
    generated.mkdir(parents=True)
    (generated / "ghost.mapinfo").write_text(_GENERATED)
    assert MapCatalogue(game, userdir).maps() == []
