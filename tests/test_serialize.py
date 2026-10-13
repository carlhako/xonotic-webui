"""Cvar-name validation and the value serialiser (design D4)."""

from __future__ import annotations

import pytest

from xonotic_webui.serversettings.serialize import (
    MAX_VALUE_LENGTH,
    InvalidCvarNameError,
    InvalidValueError,
    assignment,
    is_valid_name,
    quote,
    validate_name,
    validate_value,
)


@pytest.mark.parametrize("name", ["hostname", "g_balance_health_start", "_x", "a.b", "CamelCase9"])
def test_plain_cvar_names_are_accepted(name: str) -> None:
    assert validate_name(name) == name


@pytest.mark.parametrize(
    "name",
    ["", "has space", "semi;colon", "9starts", 'quo"te', "new\nline", "a-b", "$x", "x" * 101],
)
def test_other_names_are_rejected(name: str) -> None:
    with pytest.raises(InvalidCvarNameError):
        validate_name(name)
    assert not is_valid_name(name)


@pytest.mark.parametrize(
    "value",
    [
        "Welcome; have fun",
        "$hostname rocks",
        "// not a comment",
        "^1Red ^xF80Server",
        "",
        "  padded  ",
        "unicode: ünï ✓",
        "a" * MAX_VALUE_LENGTH,
    ],
)
def test_hostile_but_plain_values_are_accepted(value: str) -> None:
    assert validate_value(value) == value


@pytest.mark.parametrize(
    ("value", "named"),
    [
        ("two\nlines", "line break"),
        ("carriage\rreturn", "carriage return"),
        ("tab\there", "tab"),
        ('say "hi"', "double quote"),
        ("back\\slash", "backslash"),
        ("bell\x07", "U\\+0007"),
        ("del\x7f", "U\\+007F"),
    ],
)
def test_disallowed_characters_are_rejected_and_named(value: str, named: str) -> None:
    with pytest.raises(InvalidValueError, match=named):
        validate_value(value)


def test_overlong_values_are_rejected() -> None:
    with pytest.raises(InvalidValueError, match="at most"):
        validate_value("a" * (MAX_VALUE_LENGTH + 1))


@pytest.mark.parametrize(
    ("value", "line"),
    [
        ("Welcome; have fun", 'sv_motd "Welcome; have fun"'),
        ("$hostname rocks", 'sv_motd "$$hostname rocks"'),
        ("price $5 $$", 'sv_motd "price $$5 $$$$"'),
        ("a // b", 'sv_motd "a // b"'),
        ("^1Red ^xF80Server", 'sv_motd "^1Red ^xF80Server"'),
        ("", 'sv_motd ""'),
    ],
)
def test_values_are_always_quoted_and_dollars_doubled(value: str, line: str) -> None:
    assert assignment("sv_motd", value) == line


def test_raw_overrides_use_the_set_form() -> None:
    assert assignment("g_custom", "1", create=True) == 'set g_custom "1"'


def test_nothing_can_leave_the_quotes() -> None:
    # No accepted value contains a double quote or a backslash, so the closing quote of
    # the written token is always the last quote on the line.
    for value in ["a;b", "a$b", "a//b", "a b", "^7x"]:
        token = quote(value)
        assert token.startswith('"') and token.endswith('"')
        assert '"' not in token[1:-1]
