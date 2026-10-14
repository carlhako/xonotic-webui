"""Release version parsing and comparison (panel-self-update; design D1).

Only ``vMAJOR.MINOR.PATCH`` (the leading ``v`` optional) is understood. Anything
else is *unknown*: it is never treated as an available update. That is enough
for this project's tags and avoids a dependency on ``packaging``.
"""

from __future__ import annotations

import re

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version(text: str | None) -> tuple[int, int, int] | None:
    """``"v1.2.3"`` / ``"1.2.3"`` -> ``(1, 2, 3)``; anything else -> ``None``."""
    if not text:
        return None
    m = _VERSION_RE.match(text.strip())
    if m is None:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def is_newer(latest: str | None, current: str | None) -> bool | None:
    """Whether ``latest`` is strictly newer than ``current``.

    ``None`` when either side does not parse, meaning availability is unknown.
    A running version newer than the latest release (a development build) is
    ``False``, not an update.
    """
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return None
    return a > b
