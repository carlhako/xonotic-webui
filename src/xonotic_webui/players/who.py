"""The reply of ``sv_cmd who "|"``: every connected slot with its key fingerprint.

Run from the server console, so ``sv_status_privacy`` masks nothing. Captured from a 0.8.6
dedicated server (``tests/fixtures/xonotic/who_reply.txt``)::

    List of client information:
    |ent |nickname            |ping |pl |time     |ip              |crypto_id|
    |#1  |^1Spike^7Tester     |33   |0  |00:00:27 |127.0.0.1       |dRXbA...Sa=|
    |#2  |[BOT]Eureka        |0    |0  |00:00:27 |null/botclient  |null/botclient|
    Finished listing 2 client(s) out of 16 slots.

The nickname is cut to 20 characters and may itself contain ``|``, so a row is split taking
fields from the right: the last non-empty field is the fingerprint, the one before it the
address. The panel never keeps the address.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from xonotic_webui.colors import strip_colors

_NONE_VALUES = frozenset({"", "null/botclient", "hidden"})
_ROW = re.compile(r"^\|\s*#(?P<ent>\d+)\s*\|")


@dataclass(frozen=True)
class WhoRow:
    ent: int
    fingerprint: str | None  # ``None`` for bots, hidden and empty values


class WhoReplyCollector:
    """Collects one ``who`` reply. Feed it each console line (see ``Console.query``)."""

    def __init__(self) -> None:
        self.rows: dict[int, WhoRow] = {}
        self._started = False
        self._done = False

    @property
    def done(self) -> bool:
        return self._done

    def feed(self, raw_line: str) -> bool:
        """Whether ``raw_line`` was part of the reply (and so should be withheld)."""
        if self._done:
            return False
        plain = strip_colors(raw_line).strip("\r")
        if not self._started:
            if plain.strip().startswith("List of client information"):
                self._started = True
                return True
            return False
        stripped = plain.strip()
        if stripped.startswith("Finished listing"):
            self._done = True
            return True
        m = _ROW.match(stripped)
        if m is not None:
            fields = [f.strip() for f in stripped.split("|")]
            # ``|#1 |name |ping |pl |time |ip |crypto_id|`` splits into a leading and a
            # trailing empty string around the columns. The last column is the key, taken
            # from the right so a ``|`` inside the nickname cannot shift it.
            fingerprint = fields[-2] if len(fields) >= 4 and fields[-1] == "" else ""
            self.rows[int(m.group("ent"))] = WhoRow(
                ent=int(m.group("ent")),
                fingerprint=None if fingerprint in _NONE_VALUES else fingerprint,
            )
            return True
        if stripped.startswith("|") or stripped == "":
            return True  # the column header and padding
        return False
