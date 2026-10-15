"""The match clock and the score limit, from one poll's values (design D3, D6).

The server clock and the match start time are read from the game each tick, so a panel
restart mid-match, an admin time change or an overtime is followed without any state.
Values are whole seconds, so a snapshot changes once a second.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from xonotic_webui.serversettings.registry import GAMETYPES_BY_ID

DEFAULT_SCORE_UNIT = "points"


def _flag(values: Mapping[str, float], name: str) -> bool:
    return bool(values.get(name, 0))


def unavailable_clock() -> dict[str, Any]:
    return {
        "available": False,
        "phase": None,
        "paused": False,
        "time_limit_s": None,
        "left_s": None,
        "elapsed_s": None,
        "overtimes": 0,
    }


def compute_clock(
    values: Mapping[str, float], timelimit_minutes: float | None, *, paused: bool = False
) -> dict[str, Any]:
    """The clock for one poll. ``values`` holds the game's globals by name.

    * ``ended``: the match-over scoreboard is showing (``intermission_running`` or
      ``game_stopped``); no time left.
    * ``warmup``: ``warmup_stage`` is set; ``game_starttime`` is 0 then, so what is left is
      ``warmup_limit - time`` (when warmup has a limit).
    * ``countdown``: ``time`` has not reached ``game_starttime`` yet.
    * ``playing``, or ``overtime`` once ``checkrules_overtimesadded`` is above 0; the time
      left is the live time limit less the time since the match start. The limit is read
      from the cvar every tick, which is how a raised limit is followed.
    """
    if "time" not in values or "game_starttime" not in values:
        return unavailable_clock()
    now = values["time"]
    start = values["game_starttime"]
    overtimes = int(values.get("checkrules_overtimesadded", 0))
    limit_s = round(timelimit_minutes * 60) if timelimit_minutes and timelimit_minutes > 0 else None

    clock = unavailable_clock()
    clock.update(available=True, paused=paused, time_limit_s=limit_s, overtimes=max(overtimes, 0))

    if _flag(values, "intermission_running") or _flag(values, "game_stopped"):
        clock["phase"] = "ended"
    elif _flag(values, "warmup_stage"):
        clock["phase"] = "warmup"
        warmup_limit = values.get("warmup_limit", 0)
        if warmup_limit > 0:
            clock["left_s"] = max(0, math.ceil(start + warmup_limit - now))
    elif now < start:
        clock["phase"] = "countdown"
        clock["left_s"] = max(0, math.ceil(start - now))
    else:
        clock["phase"] = "overtime" if overtimes > 0 else "playing"
        elapsed = now - start
        clock["elapsed_s"] = max(0, math.floor(elapsed))
        if limit_s is not None:
            clock["left_s"] = max(0, math.ceil(limit_s - elapsed))
    return clock


def compute_score_limit(fraglimit: float | None, gametype: str | None) -> dict[str, Any]:
    """The live score limit and what it counts. ``fraglimit`` carries the active limit of
    every gametype (captures in CTF, points in TDM); 0 means there is none."""
    entry = GAMETYPES_BY_ID.get(gametype) if gametype else None
    unit = entry.score_unit if entry is not None else DEFAULT_SCORE_UNIT
    value = int(fraglimit) if fraglimit is not None and fraglimit > 0 else None
    return {"value": value, "unit": unit}
