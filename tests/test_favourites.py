"""The favourite maps: the store and its routes (map-favourites spec)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from tests.conftest import Live
from xonotic_webui.maps.favourites import FavouritesStore, InvalidFavouriteError

LiveFactory = Callable[..., "asyncio.Future[Live]"]


# --- 4.1 the store ------------------------------------------------------------------------


async def test_favourites_round_trip_through_the_file(tmp_path: Path) -> None:
    path = tmp_path / "state" / "favourites.json"
    store = FavouritesStore(path)
    assert store.maps() == []
    assert await store.add("boil") == ["boil"]
    assert await store.add("warfare") == ["boil", "warfare"]
    assert json.loads(path.read_text())["maps"] == ["boil", "warfare"]
    # a fresh store (a panel restart) reads the same list
    assert FavouritesStore(path).maps() == ["boil", "warfare"]
    assert not list(path.parent.glob("*.tmp"))  # written to a temp file and renamed


async def test_adding_twice_and_removing_an_absent_name_change_nothing(tmp_path: Path) -> None:
    store = FavouritesStore(tmp_path / "favourites.json")
    await store.add("boil")
    assert await store.add("boil") == ["boil"]
    assert await store.remove("never_starred") == ["boil"]
    assert await store.remove("boil") == []
    assert await store.remove("boil") == []


@pytest.mark.parametrize("name", ["", "has space", "../x", "a;b", "x" * 200])
async def test_an_invalid_name_is_refused_and_nothing_is_written(tmp_path: Path, name: str) -> None:
    path = tmp_path / "favourites.json"
    store = FavouritesStore(path)
    with pytest.raises(InvalidFavouriteError):
        await store.add(name)
    with pytest.raises(InvalidFavouriteError):
        await store.remove(name)
    assert not path.exists()


@pytest.mark.parametrize(
    "content", ["", "not json", "[]", '{"maps": "boil"}', '{"maps": [1, 2]}', '{"nomaps": []}']
)
async def test_a_corrupt_file_is_empty_and_is_replaced_by_the_next_change(
    tmp_path: Path, content: str, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "favourites.json"
    path.write_text(content)
    store = FavouritesStore(path)
    with caplog.at_level("WARNING"):
        assert store.maps() == []
    assert any("favourites" in r.message for r in caplog.records)
    assert await store.add("boil") == ["boil"]
    assert FavouritesStore(path).maps() == ["boil"]


async def test_a_favourite_of_a_map_that_is_not_installed_is_kept(tmp_path: Path) -> None:
    store = FavouritesStore(tmp_path / "favourites.json")
    await store.add("long_gone_map")  # no catalogue is consulted
    assert store.maps() == ["long_gone_map"]


# --- 4.2 the routes -----------------------------------------------------------------------


async def test_star_and_unstar_through_the_api_while_the_server_is_stopped(
    live: LiveFactory,
) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        assert (await client.get("/api/status")).json()["state"] == "stopped"
        assert (await client.get("/api/favourites")).json() == {"maps": []}
        r = await client.put("/api/favourites/boil")
        assert (r.status_code, r.json()) == (200, {"maps": ["boil"]})
        assert (await client.put("/api/favourites/boil")).json() == {"maps": ["boil"]}
        assert (await client.get("/api/favourites")).json() == {"maps": ["boil"]}
        assert (await client.delete("/api/favourites/boil")).json() == {"maps": []}
        assert (await client.delete("/api/favourites/boil")).status_code == 200


async def test_a_bad_name_is_a_422_with_a_code(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.put("/api/favourites/has%20space")
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "invalid_map_name"
        assert (await client.get("/api/favourites")).json() == {"maps": []}


async def test_concurrent_adds_all_survive(live: LiveFactory) -> None:
    app = await live()
    names = [f"map_{i}" for i in range(25)]
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        results = await asyncio.gather(*(client.put(f"/api/favourites/{n}") for n in names))
        assert all(r.status_code == 200 for r in results)
        assert (await client.get("/api/favourites")).json()["maps"] == sorted(names)


async def test_favourites_survive_a_panel_restart(live: LiveFactory) -> None:
    first = await live()
    async with httpx.AsyncClient(base_url=first.base_url) as client:
        await client.put("/api/favourites/boil")
    # a second panel process over the same state directory
    second = await live()
    assert second.settings.state_dir == first.settings.state_dir
    async with httpx.AsyncClient(base_url=second.base_url) as client:
        assert (await client.get("/api/favourites")).json() == {"maps": ["boil"]}
