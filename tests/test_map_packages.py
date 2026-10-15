"""The map package store: upload validation, install, lookup and removal (map-packages spec)."""

from __future__ import annotations

import io
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.helpers import write_pk3
from xonotic_webui.maps.catalogue import MapCatalogue
from xonotic_webui.maps.packages import (
    AlreadyExistsError,
    BadFilenameError,
    NoMapError,
    NotAPackageError,
    NotPk3Error,
    PackageNotFoundError,
    PackageStore,
    TooLargeError,
)


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    game = tmp_path / "game"
    userdir = tmp_path / "state" / "userdir"
    (game / "data").mkdir(parents=True)
    return game, userdir


@pytest.fixture
def store(roots: tuple[Path, Path]) -> PackageStore:
    game, userdir = roots
    return PackageStore(userdir / "data", MapCatalogue(game, userdir))


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def valid_zip(*maps: str) -> bytes:
    return zip_bytes({f"maps/{m}.bsp": b"BSP" for m in maps})


async def body(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


async def failing_body(first: bytes) -> AsyncIterator[bytes]:
    yield first
    raise ConnectionError("client went away")


def only_files(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []


# --- 2.1 validation and install -----------------------------------------------------------


async def test_a_valid_package_is_installed_and_reports_its_maps(
    store: PackageStore, roots: tuple[Path, Path]
) -> None:
    _, userdir = roots
    data = valid_zip("mymap", "othermap")
    half = len(data) // 2  # streamed in more than one piece
    result = await store.install("mymap_v2.pk3", body(data[:half], data[half:]))
    assert (result.name, result.size, result.maps) == (
        "mymap_v2.pk3",
        len(data),
        ("mymap", "othermap"),
    )
    assert result.duplicates == ()
    assert (userdir / "data" / "mymap_v2.pk3").read_bytes() == data
    assert only_files(userdir / "data") == ["mymap_v2.pk3"]  # no temp file left


@pytest.mark.parametrize("name", ["maps.zip", "mymap.bsp", "mymap", "MYMAP.PK3", "x.pk3.zip"])
async def test_other_file_types_are_refused(
    store: PackageStore, roots: tuple[Path, Path], name: str
) -> None:
    _, userdir = roots
    with pytest.raises(NotPk3Error, match=r"\.pk3"):
        await store.install(name, body(valid_zip("m")))
    assert only_files(userdir / "data") == []


@pytest.mark.parametrize(
    "name",
    [
        "../x.pk3",
        "a/b.pk3",
        "/etc/x.pk3",
        "a b.pk3",
        ".hidden.pk3",
        ".pk3",
        "a\\b.pk3",
        "x" * 101 + ".pk3",
    ],
)
async def test_an_unsafe_file_name_is_refused(
    store: PackageStore, roots: tuple[Path, Path], name: str
) -> None:
    _, userdir = roots
    with pytest.raises(BadFilenameError):
        await store.install(name, body(valid_zip("m")))
    assert only_files(userdir / "data") == []
    assert not (userdir.parent / "x.pk3").exists()


async def test_a_package_over_the_limit_is_refused_and_leaves_no_file(
    roots: tuple[Path, Path],
) -> None:
    game, userdir = roots
    small = PackageStore(userdir / "data", MapCatalogue(game, userdir), max_bytes=1000)
    data = valid_zip("m") + b"\0" * 2000
    with pytest.raises(TooLargeError, match="limit"):
        await small.install("big.pk3", body(data[:600], data[600:]))
    assert only_files(userdir / "data") == []
    # refused before reading when the declared size already says so
    with pytest.raises(TooLargeError):
        await small.install("big.pk3", body(b"never read"), declared_size=5000)
    assert only_files(userdir / "data") == []


async def test_a_lying_declared_size_does_not_defeat_the_limit(roots: tuple[Path, Path]) -> None:
    game, userdir = roots
    small = PackageStore(userdir / "data", MapCatalogue(game, userdir), max_bytes=1000)
    with pytest.raises(TooLargeError):
        await small.install("big.pk3", body(b"x" * 3000), declared_size=10)
    assert only_files(userdir / "data") == []


@pytest.mark.parametrize(
    ("data", "error"),
    [
        (b"this is not a zip", NotAPackageError),
        (b"", NotAPackageError),
        (zip_bytes({"readme.txt": b"hi"}), NoMapError),
        (zip_bytes({"maps/_hudsetup.bsp": b"BSP"}), NoMapError),
        (zip_bytes({"maps/deep/m.bsp": b"BSP", "textures/m.bsp": b"BSP"}), NoMapError),
        (zip_bytes({"../x": b"evil", "maps/m.bsp": b"BSP"}), NotAPackageError),
        (zip_bytes({"/abs/x": b"evil", "maps/m.bsp": b"BSP"}), NotAPackageError),
    ],
)
async def test_a_file_that_is_not_a_usable_package_is_refused(
    store: PackageStore, roots: tuple[Path, Path], data: bytes, error: type[Exception]
) -> None:
    _, userdir = roots
    with pytest.raises(error):
        await store.install("fake.pk3", body(data))
    assert only_files(userdir / "data") == []


async def test_a_name_that_is_installed_is_not_replaced(
    store: PackageStore, roots: tuple[Path, Path]
) -> None:
    _, userdir = roots
    original = write_pk3(userdir / "data" / "mymap_v2.pk3", {"mymap": {"gametypes": ["dm"]}})
    before = original.read_bytes()
    with pytest.raises(AlreadyExistsError, match="already installed"):
        await store.install("mymap_v2.pk3", body(valid_zip("other")))
    assert original.read_bytes() == before
    assert only_files(userdir / "data") == ["mymap_v2.pk3"]


async def test_the_install_itself_never_overwrites_a_package_that_appears_meanwhile(
    store: PackageStore, roots: tuple[Path, Path]
) -> None:
    _, userdir = roots
    target = userdir / "data" / "race.pk3"

    async def racing() -> AsyncIterator[bytes]:
        yield valid_zip("mine")
        target.write_bytes(b"someone else's file")  # lands while the upload is streaming

    with pytest.raises(AlreadyExistsError):
        await store.install("race.pk3", racing())
    assert target.read_bytes() == b"someone else's file"
    assert only_files(userdir / "data") == ["race.pk3"]


async def test_an_interrupted_upload_leaves_nothing(
    store: PackageStore, roots: tuple[Path, Path]
) -> None:
    _, userdir = roots
    with pytest.raises(ConnectionError):
        await store.install("mymap.pk3", failing_body(valid_zip("m")[:20]))
    assert only_files(userdir / "data") == []


# --- 2.2 duplicates -----------------------------------------------------------------------


async def test_a_map_with_a_game_maps_name_is_reported_and_used(
    store: PackageStore, roots: tuple[Path, Path]
) -> None:
    game, _ = roots
    write_pk3(game / "data" / "stock.pk3", {"boil": {"gametypes": ["dm"]}})
    result = await store.install("my_boil.pk3", body(valid_zip("boil", "fresh")))
    assert [(d.map, d.package, d.source, d.used) for d in result.duplicates] == [
        ("boil", "stock.pk3", "game", True)
    ]


async def test_a_map_with_another_user_packages_name_says_which_one_wins(
    store: PackageStore, roots: tuple[Path, Path]
) -> None:
    _, userdir = roots
    write_pk3(userdir / "data" / "m.pk3", {"shared": {"gametypes": ["dm"]}})
    later = await store.install("z.pk3", body(valid_zip("shared")))
    assert [(d.map, d.package, d.source, d.used) for d in later.duplicates] == [
        ("shared", "m.pk3", "user", True)
    ]
    # an earlier file name loses to the one already installed
    write_pk3(userdir / "data" / "q.pk3", {"other": {"gametypes": ["dm"]}})
    earlier = await store.install("a.pk3", body(valid_zip("other")))
    assert [(d.map, d.package, d.used) for d in earlier.duplicates] == [("other", "q.pk3", False)]


# --- 2.3 stale temp files -----------------------------------------------------------------


def test_stale_upload_files_are_removed_at_startup_and_packages_are_kept(
    store: PackageStore, roots: tuple[Path, Path]
) -> None:
    _, userdir = roots
    data = userdir / "data"
    keep = write_pk3(data / "keep.pk3", {"keep": {"gametypes": ["dm"]}})
    (data / ".upload-deadbeef.part").write_bytes(b"half")
    (data / ".upload-cafe.part").write_bytes(b"")
    (data / "notes.txt").write_text("not ours")
    assert store.clean_stale_uploads() == 2
    assert only_files(data) == ["keep.pk3", "notes.txt"]
    assert zipfile.is_zipfile(keep)
    assert store.clean_stale_uploads() == 0


def test_cleaning_with_no_data_directory_is_a_no_op(store: PackageStore) -> None:
    assert store.clean_stale_uploads() == 0


# --- 2.4 download and delete lookup -------------------------------------------------------


def test_a_user_package_resolves_and_deleting_it_returns_its_maps(
    store: PackageStore, roots: tuple[Path, Path]
) -> None:
    _, userdir = roots
    pk3 = write_pk3(
        userdir / "data" / "pair.pk3", {"one": {"gametypes": ["dm"]}, "two": {"gametypes": ["dm"]}}
    )
    assert store.resolve("pair.pk3") == pk3
    assert store.delete("pair.pk3") == ("one", "two")
    assert not pk3.exists()


@pytest.mark.parametrize(
    "name",
    ["stock.pk3", "../stock.pk3", "/etc/passwd", "nosuch.pk3", "adir.pk3", "", "..", "a/b.pk3"],
)
def test_anything_but_a_user_package_is_not_found_and_nothing_is_touched(
    store: PackageStore, roots: tuple[Path, Path], name: str
) -> None:
    game, userdir = roots
    write_pk3(game / "data" / "stock.pk3", {"boil": {"gametypes": ["dm"]}})
    (userdir / "data").mkdir(parents=True, exist_ok=True)
    (userdir / "data" / "adir.pk3").mkdir()
    (userdir / "outside.pk3").write_bytes(b"x")
    before = {p: p.stat().st_mtime_ns for p in game.rglob("*")} | {
        p: p.stat().st_mtime_ns for p in userdir.rglob("*")
    }
    with pytest.raises(PackageNotFoundError):
        store.resolve(name)
    with pytest.raises(PackageNotFoundError):
        store.delete(name)
    after = {p: p.stat().st_mtime_ns for p in game.rglob("*")} | {
        p: p.stat().st_mtime_ns for p in userdir.rglob("*")
    }
    assert before == after
    assert (game / "data" / "stock.pk3").exists() and (userdir / "outside.pk3").exists()


def test_deleting_reveals_the_game_map_it_shadowed(
    store: PackageStore, roots: tuple[Path, Path]
) -> None:
    game, userdir = roots
    write_pk3(game / "data" / "stock.pk3", {"boil": {"title": "Stock", "gametypes": ["dm"]}})
    write_pk3(userdir / "data" / "mine.pk3", {"boil": {"title": "Mine", "gametypes": ["dm"]}})
    catalogue = MapCatalogue(game, userdir)
    packages = PackageStore(userdir / "data", catalogue)
    assert catalogue.get("boil").source == "user"  # type: ignore[union-attr]
    packages.delete("mine.pk3")
    entry = catalogue.get("boil")
    assert entry is not None and (entry.source, entry.title) == ("game", "Stock")


def test_a_symlink_to_a_package_outside_is_still_only_a_name_in_the_directory(
    store: PackageStore, roots: tuple[Path, Path], tmp_path: Path
) -> None:
    _, userdir = roots
    elsewhere = write_pk3(tmp_path / "elsewhere" / "real.pk3", {"m": {"gametypes": ["dm"]}})
    (userdir / "data").mkdir(parents=True, exist_ok=True)
    (userdir / "data" / "linked.pk3").symlink_to(elsewhere)
    # the operator put it there, so it is a package of the user directory like any other
    assert store.resolve("linked.pk3") == userdir / "data" / "linked.pk3"
    assert store.delete("linked.pk3") == ("m",)
    assert elsewhere.exists()  # only the link was removed
