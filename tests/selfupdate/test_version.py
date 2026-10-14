"""panel-self-update: version parsing and comparison."""

from __future__ import annotations

import pytest

from xonotic_webui.selfupdate.version import is_newer, parse_version


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0.4.0", (0, 4, 0)),
        ("v0.4.0", (0, 4, 0)),
        ("v10.20.30", (10, 20, 30)),
        (" v1.2.3 ", (1, 2, 3)),
        ("", None),
        (None, None),
        ("v1.2", None),
        ("1.2.3-rc1", None),
        ("latest", None),
        ("vv1.2.3", None),
    ],
)
def test_parse_version(text, expected) -> None:
    assert parse_version(text) == expected


def test_newer_release_is_an_update() -> None:
    assert is_newer("v0.5.0", "0.4.0") is True
    assert is_newer("0.10.0", "0.9.9") is True  # numeric, not lexical


def test_equal_release_is_not_an_update() -> None:
    assert is_newer("v0.4.0", "0.4.0") is False


def test_older_release_than_a_dev_build_is_not_an_update() -> None:
    assert is_newer("v0.4.0", "0.5.0") is False


def test_unparseable_input_is_unknown() -> None:
    assert is_newer("nightly", "0.4.0") is None
    assert is_newer("v0.5.0", "0.5.0.dev1") is None
