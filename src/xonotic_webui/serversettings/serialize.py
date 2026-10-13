"""Cvar-name and value validation, and the one serialiser for console lines (design D4).

Verified console parsing rules (config file and stdin alike): ``;`` and ``//`` inside
double quotes are literal, ``$name`` expands even inside quotes while ``$$`` is a literal
``$``, ``\\"`` is a literal quote and an unquoted value is cut at the first space.

The panel therefore accepts only single-line values without control characters, ``"``
or ``\\``, always writes ``name "value"`` and doubles every ``$``. It rejects rather than
escapes the characters whose handling is engine-specific, so no value can end the quote
and start a second command.
"""

from __future__ import annotations

import re

MAX_VALUE_LENGTH = 1000
MAX_NAME_LENGTH = 100

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


class InvalidCvarNameError(ValueError):
    code = "invalid_cvar_name"


class InvalidValueError(ValueError):
    code = "invalid_value"


def validate_name(name: str) -> str:
    """Return ``name`` if it is a plain cvar name, else raise :class:`InvalidCvarNameError`."""
    if not isinstance(name, str) or not name:
        raise InvalidCvarNameError("a cvar name must not be empty")
    if len(name) > MAX_NAME_LENGTH:
        raise InvalidCvarNameError(f"a cvar name must be at most {MAX_NAME_LENGTH} characters")
    if _NAME.match(name) is None:
        raise InvalidCvarNameError(
            "a cvar name must start with a letter or underscore and contain only "
            "letters, digits, underscores and dots"
        )
    return name


def is_valid_name(name: str) -> bool:
    try:
        validate_name(name)
    except InvalidCvarNameError:
        return False
    return True


def _describe(char: str) -> str:
    if char == "\n":
        return "a line break"
    if char == "\r":
        return "a carriage return"
    if char == "\t":
        return "a tab"
    if char == '"':
        return 'a double quote (")'
    if char == "\\":
        return "a backslash (\\)"
    return f"the control character U+{ord(char):04X}"


def validate_value(value: str) -> str:
    """Return ``value`` if the console can be given it verbatim, else raise.

    The error names the first disallowed character.
    """
    if not isinstance(value, str):
        raise InvalidValueError("a value must be text")
    if len(value) > MAX_VALUE_LENGTH:
        raise InvalidValueError(f"a value must be at most {MAX_VALUE_LENGTH} characters")
    for char in value:
        if char in ('"', "\\") or ord(char) < 0x20 or ord(char) == 0x7F:
            raise InvalidValueError(f"a value must not contain {_describe(char)}")
    return value


def quote(value: str) -> str:
    """``value`` as one quoted console token: validated, ``$`` doubled."""
    return '"' + validate_value(value).replace("$", "$$") + '"'


def assignment(name: str, value: str, *, create: bool = False) -> str:
    """A console line that sets cvar ``name`` to ``value``.

    ``create`` uses ``set`` so an unknown cvar is created (raw overrides); curated
    settings name cvars the game defines and use the plain form.
    """
    line = f"{validate_name(name)} {quote(value)}"
    return f"set {line}" if create else line
