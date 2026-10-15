"""Map package routes against a live panel: upload, download and delete (map-packages spec)."""

from __future__ import annotations

import asyncio
import io
import zipfile
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest

from tests.conftest import Live
from tests.helpers import write_pk3
from xonotic_webui.maps import packages

LiveFactory = Callable[..., "asyncio.Future[Live]"]


def make_zip(*maps: str, extra: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in maps:
            zf.writestr(f"maps/{name}.bsp", b"BSP")
            zf.writestr(f"maps/{name}.mapinfo", f"title {name.title()}\ngametype dm 20 5 5\n")
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


async def wait_state(client: httpx.AsyncClient, want: str, timeout: float = 15.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while (await client.get("/api/status")).json()["state"] != want:
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"state never became {want!r}")
        await asyncio.sleep(0.05)


def leftovers(app: Live) -> list[str]:
    data = app.settings.userdir / "data"
    return sorted(p.name for p in data.iterdir()) if data.is_dir() else []


async def maps_by_name(client: httpx.AsyncClient) -> dict[str, dict]:
    return {m["name"]: m for m in (await client.get("/api/maps")).json()["maps"]}


# --- 3.1 upload ---------------------------------------------------------------------------


async def test_an_uploaded_package_is_installed_and_its_maps_are_listed(
    live: LiveFactory,
) -> None:
    app = await live()
    data = make_zip("mymap", "othermap")
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        assert "mymap" not in await maps_by_name(client)
        r = await client.put("/api/packages/mymap_v2.pk3", content=data)
        assert r.status_code == 200
        assert r.json() == {
            "name": "mymap_v2.pk3",
            "size": len(data),
            "maps": ["mymap", "othermap"],
            "duplicates": [],
            "restart_required": False,  # the server is stopped: the next start loads it
        }
        listed = await maps_by_name(client)
        assert listed["mymap"]["package"] == "mymap_v2.pk3"
        assert listed["mymap"]["package_size"] == len(data)
        assert listed["mymap"]["source"] == "user"
        assert listed["mymap"]["pending_restart"] is False
    assert leftovers(app) == ["mymap_v2.pk3"]


async def test_an_upload_while_running_is_pending_until_the_server_restarts(
    live: LiveFactory,
) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        await client.post("/api/lifecycle/start")
        await wait_state(client, "running")
        r = await client.put("/api/packages/late.pk3", content=make_zip("latemap"))
        assert r.status_code == 200 and r.json()["restart_required"] is True
        assert (await maps_by_name(client))["latemap"]["pending_restart"] is True
        await client.post("/api/lifecycle/restart")
        await wait_state(client, "running")
        assert (await maps_by_name(client))["latemap"]["pending_restart"] is False
        await client.post("/api/lifecycle/stop")


@pytest.mark.parametrize(
    ("name", "status", "code"),
    [
        ("maps.zip", 422, "not_pk3"),
        ("mymap.bsp", 422, "not_pk3"),
        ("mymap", 422, "not_pk3"),
        ("a%20b.pk3", 422, "bad_filename"),
        (".hidden.pk3", 422, "bad_filename"),
        ("..%2Fevil.pk3", 422, "bad_filename"),
        ("sub%2Fevil.pk3", 422, "bad_filename"),
    ],
)
async def test_unusable_names_are_rejected_with_a_stable_code(
    live: LiveFactory, name: str, status: int, code: str
) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.put(f"/api/packages/{name}", content=make_zip("m"))
        assert r.status_code == status
        assert r.json()["detail"]["code"] == code
    assert leftovers(app) == []
    assert not (app.settings.state_dir / "evil.pk3").exists()


async def test_content_errors_each_have_their_own_code(live: LiveFactory) -> None:
    app = await live()
    cases = {
        "not_a_package": b"this is not a zip file",
        "no_map": make_zip(extra={"readme.txt": b"hello"}),
    }
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        for code, data in cases.items():
            r = await client.put("/api/packages/fake.pk3", content=data)
            assert (r.status_code, r.json()["detail"]["code"]) == (422, code)
        unsafe = make_zip("m", extra={"../evil": b"x"})
        r = await client.put("/api/packages/unsafe.pk3", content=unsafe)
        assert (r.status_code, r.json()["detail"]["code"]) == (422, "not_a_package")
    assert leftovers(app) == []


async def test_a_name_that_exists_is_a_conflict_and_the_package_is_unchanged(
    live: LiveFactory,
) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        first = make_zip("one")
        assert (await client.put("/api/packages/dup.pk3", content=first)).status_code == 200
        r = await client.put("/api/packages/dup.pk3", content=make_zip("two"))
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "already_exists"
    assert (app.settings.userdir / "data" / "dup.pk3").read_bytes() == first
    assert leftovers(app) == ["dup.pk3"]


async def test_a_map_named_like_a_game_map_is_reported(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.put("/api/packages/my_boil.pk3", content=make_zip("boil"))
        assert r.status_code == 200
        assert r.json()["duplicates"] == [
            {"map": "boil", "package": "xonotic-data-maps.pk3", "source": "game", "used": True}
        ]


async def test_the_limit_is_enforced_with_and_without_a_content_length(
    live: LiveFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(packages, "MAX_PACKAGE_BYTES", 4096)
    app = await live()
    app.runtime.package_store._max = 4096
    big = make_zip("m", extra={"pad.bin": b"\0" * 8_000_000})

    async def chunks() -> AsyncIterator[bytes]:
        for i in range(0, len(big), 65536):
            yield big[i : i + 65536]

    async with httpx.AsyncClient(base_url=app.base_url) as client:
        # a declared size over the limit is refused before the body is read
        r = await client.put("/api/packages/big.pk3", content=big)
        assert (r.status_code, r.json()["detail"]["code"]) == (413, "too_large")
        # no Content-Length (chunked): counted while streaming
        r = await client.put("/api/packages/big.pk3", content=chunks())
        assert (r.status_code, r.json()["detail"]["code"]) == (413, "too_large")
    assert leftovers(app) == []


async def test_a_client_that_disconnects_mid_upload_leaves_nothing(live: LiveFactory) -> None:
    app = await live()
    host, port = app.base_url.removeprefix("http://").split(":")
    reader, writer = await asyncio.open_connection(host, int(port))
    data = make_zip("m", extra={"pad.bin": b"\0" * 100_000})
    head = (
        f"PUT /api/packages/half.pk3 HTTP/1.1\r\nHost: x\r\n"
        f"Content-Length: {len(data)}\r\nContent-Type: application/octet-stream\r\n\r\n"
    )
    writer.write(head.encode() + data[:1000])
    await writer.drain()
    await asyncio.sleep(0.2)
    writer.close()
    await writer.wait_closed()
    deadline = asyncio.get_running_loop().time() + 5
    while leftovers(app):
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"left behind: {leftovers(app)}")
        await asyncio.sleep(0.05)
    del reader


# --- 3.2 download and delete ----------------------------------------------------------------


async def test_a_user_package_downloads_byte_for_byte(live: LiveFactory) -> None:
    app = await live()
    data = make_zip("mymap")
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        await client.put("/api/packages/mymap_v2.pk3", content=data)
        r = await client.get("/api/packages/mymap_v2.pk3")
        assert r.status_code == 200
        assert r.content == data
        assert r.headers["content-disposition"].startswith("attachment")
        assert 'filename="mymap_v2.pk3"' in r.headers["content-disposition"]


async def test_deleting_a_package_removes_its_maps_and_reveals_the_shadowed_game_map(
    live: LiveFactory,
) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        stock = (await maps_by_name(client))["boil"]
        assert stock["source"] == "game"
        await client.put("/api/packages/mine.pk3", content=make_zip("boil", "extra"))
        listed = await maps_by_name(client)
        assert listed["boil"]["source"] == "user" and "extra" in listed

        r = await client.delete("/api/packages/mine.pk3")
        assert r.status_code == 200
        assert r.json() == {"name": "mine.pk3", "maps": ["boil", "extra"]}
        listed = await maps_by_name(client)
        assert "extra" not in listed
        assert listed["boil"]["source"] == "game"
    assert leftovers(app) == []


@pytest.mark.parametrize(
    "name", ["xonotic-data-maps.pk3", "nosuch.pk3", "..%2Fx.pk3", "%2Fetc%2Fpasswd", "adir.pk3"]
)
async def test_game_packages_paths_and_unknown_names_are_not_found(
    live: LiveFactory, name: str
) -> None:
    app = await live()
    user_data = app.settings.userdir / "data"
    (user_data / "adir.pk3").mkdir(parents=True)
    game_pk3 = app.settings.game_root / "data" / "xonotic-data-maps.pk3"
    before = game_pk3.read_bytes()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        for method in (client.get, client.delete):
            r = await method(f"/api/packages/{name}")
            assert r.status_code == 404
            assert r.json()["detail"]["code"] == "package_not_found"
    assert game_pk3.read_bytes() == before
    assert (user_data / "adir.pk3").is_dir()


async def test_a_package_placed_by_hand_can_be_downloaded_and_deleted(
    live: LiveFactory,
) -> None:
    app = await live()
    pk3: Path = write_pk3(app.settings.userdir / "data" / "byhand.pk3", {"hand": None})
    expected = await asyncio.to_thread(pk3.read_bytes)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        assert (await client.get("/api/packages/byhand.pk3")).content == expected
        assert (await client.delete("/api/packages/byhand.pk3")).json()["maps"] == ["hand"]
        assert "hand" not in await maps_by_name(client)
