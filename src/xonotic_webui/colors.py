"""Xonotic colour-code handling for matching (design D10).

Xonotic embeds colour in names and messages with ``^N`` (N = 0-9), ``^xRGB`` (three hex
digits) and ``^^`` for a literal caret. A ``^`` followed by anything else, including an
``^x`` with fewer than three hex digits, is an ordinary character. The engine can also
translate codes to ANSI SGR escapes on stdout; the panel disables that, but the stripper
removes those sequences defensively so a user config cannot break matching.

The front end implements the same grammar for display (``web/src/lib/colors.ts``);
``tests/fixtures`` hold real names exercised by both.
"""

from __future__ import annotations

import re

_ANSI_SGR = re.compile(r"\x1b\[[0-9;]*m")
_CODE = re.compile(r"\^(\^|\d|x[0-9a-fA-F]{3})")
_LEADING_CODES = re.compile(r"^(?:\^\d|\^x[0-9a-fA-F]{3})+")


def strip_colors(text: str) -> str:
    """Return ``text`` as plain characters: colour codes removed, ``^^`` -> ``^``."""
    text = _ANSI_SGR.sub("", text)
    return _CODE.sub(lambda m: "^" if m.group(1) == "^" else "", text)


def strip_leading_codes(text: str) -> str:
    """Remove only the colour codes at the very start of a line.

    Every line the server prints begins with a ``^7`` reset (sometimes doubled). Event-log
    lines carry their payload, including a player name with its own codes, after that
    prefix, so the structure is matched on this form and the name is kept raw.
    """
    return _LEADING_CODES.sub("", _ANSI_SGR.sub("", text), count=1)
