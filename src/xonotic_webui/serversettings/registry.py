"""The static registries: curated settings, gametypes and reserved cvars.

Everything the frontend renders for the curated settings comes from here, via the API, so
there is a single source (design D2). Facts about the game's cvars were verified against
the 0.8.6 dedicated server (see ``openspec/changes/config-and-maps/design.md``).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Literal

# The cvars the wrapper config forces after everything else (bootstrap design D3). The
# supervisor writes exactly these, and the panel refuses to override them.
FORCED_CVARS: tuple[tuple[str, str], ...] = (
    ("sv_eventlog", "1"),
    ("sv_eventlog_console", "1"),
    ("sv_eventlog_ipv6_delimiter", "1"),
    ("sys_colortranslation", "2"),
    # The end-of-match statistics report is printed to the console, where the player
    # recorder reads it, instead of being submitted to an external statistics service.
    ("g_playerstats_gamereport_uri", "-"),
)

# ``port`` is owned by the panel's own settings (bootstrap D6) and secrets are out of
# scope here (design D1).
RESERVED_CVARS: frozenset[str] = frozenset({name for name, _ in FORCED_CVARS} | {"port"})
SECRET_CVARS: frozenset[str] = frozenset({"rcon_password"})
NOT_EDITABLE: frozenset[str] = RESERVED_CVARS | SECRET_CVARS


def is_reserved(name: str) -> bool:
    return name.lower() in NOT_EDITABLE


class ApplyClass(enum.StrEnum):
    """When a changed setting takes effect (design D2)."""

    NOW = "now"
    NEXT_MAP = "next_map"
    NEXT_START = "next_start"
    # A raw override has no known class.
    MAY_NEED_RESTART = "may_need_restart"


Kind = Literal["string", "int", "float", "bool", "choice"]


@dataclass(frozen=True)
class Choice:
    value: str
    label: str


@dataclass(frozen=True)
class CuratedSetting:
    key: str  # the cvar written to the generated config; also the setting's id
    group: str
    label: str
    help: str
    kind: Kind
    default: Any
    apply: ApplyClass
    min: float | None = None
    max: float | None = None
    max_length: int | None = None
    choices: tuple[Choice, ...] = ()
    # A bool is written as ``on`` / ``off`` (defaults ``1`` / ``0``).
    on: str = "1"
    off: str = "0"
    # The plain cvar of the running match, sent live too when the value is ``>= 0`` (D3).
    live_cvar: str | None = None
    unit: Literal["minutes", "score"] | None = None
    # Labels for special numeric values, e.g. ``-1`` = "Map default".
    value_labels: tuple[tuple[int, str], ...] = ()

    def wire(self, value: Any) -> str:
        """The value as the console text it is written as."""
        if self.kind == "bool":
            return self.on if value else self.off
        if self.kind == "float":
            return f"{float(value):g}"
        return str(value)

    @property
    def read_cvar(self) -> str:
        """The cvar whose live value shows what is in effect on the server."""
        return self.live_cvar or self.key


GROUPS: tuple[tuple[str, str], ...] = (
    ("identity", "Identity"),
    ("match", "Match"),
    ("bots", "Bots"),
    ("voting", "Voting"),
    ("mutators", "Mutators"),
    ("server", "Server"),
)

_LIMIT_LABELS = ((-1, "Map default"), (0, "No limit"))


def _mutator(cvar: str, label: str, help_text: str) -> CuratedSetting:
    return CuratedSetting(
        key=cvar,
        group="mutators",
        label=label,
        help=help_text,
        kind="bool",
        default=False,
        apply=ApplyClass.NEXT_MAP,
    )


CURATED: tuple[CuratedSetting, ...] = (
    # --- identity -------------------------------------------------------------------
    CuratedSetting(
        key="hostname",
        group="identity",
        label="Server name",
        help="Shown in the server browser and to players who connect.",
        kind="string",
        default="Xonotic 0.8.6 Server",
        apply=ApplyClass.NOW,
        max_length=100,
    ),
    CuratedSetting(
        key="sv_motd",
        group="identity",
        label="Message of the day",
        help="Shown on the welcome screen of joining players.",
        kind="string",
        default="",
        apply=ApplyClass.NOW,
        max_length=500,
    ),
    CuratedSetting(
        key="maxplayers",
        group="identity",
        label="Maximum players",
        help="Player slots, including bots. Applies when the server restarts.",
        kind="int",
        default=16,
        apply=ApplyClass.NEXT_START,
        min=1,
        max=255,
    ),
    CuratedSetting(
        key="sv_public",
        group="identity",
        label="List publicly",
        help="Advertise the server on the master server so players can find it.",
        kind="bool",
        default=True,
        apply=ApplyClass.NOW,
    ),
    # --- match limits (written as the *_override cvars so they survive map changes) ---
    CuratedSetting(
        key="timelimit_override",
        group="match",
        label="Time limit",
        help="Minutes per match. Map default uses each map's own limit; 0 plays without one.",
        kind="int",
        default=-1,
        apply=ApplyClass.NEXT_MAP,
        min=-1,
        max=1440,
        live_cvar="timelimit",
        unit="minutes",
        value_labels=_LIMIT_LABELS,
    ),
    CuratedSetting(
        key="fraglimit_override",
        group="match",
        label="Score limit",
        help=(
            "Frags, points or captures, depending on the gametype. Map default uses "
            "each map's own limit; 0 plays without one."
        ),
        kind="int",
        default=-1,
        apply=ApplyClass.NEXT_MAP,
        min=-1,
        max=100000,
        live_cvar="fraglimit",
        unit="score",
        value_labels=_LIMIT_LABELS,
    ),
    CuratedSetting(
        key="leadlimit_override",
        group="match",
        label="Lead limit",
        help=(
            "A match ends when one side leads by this much. Map default uses each map's "
            "own limit; 0 plays without one."
        ),
        kind="int",
        default=-1,
        apply=ApplyClass.NEXT_MAP,
        min=-1,
        max=100000,
        live_cvar="leadlimit",
        unit="score",
        value_labels=_LIMIT_LABELS,
    ),
    CuratedSetting(
        key="g_warmup",
        group="match",
        label="Warmup",
        help="Play a warmup stage before each match starts.",
        kind="bool",
        default=False,
        apply=ApplyClass.NEXT_MAP,
    ),
    CuratedSetting(
        key="g_warmup_limit",
        group="match",
        label="Warmup length",
        help="Seconds the warmup lasts at most. 0 lets the time limit end it, -1 never.",
        kind="int",
        default=180,
        apply=ApplyClass.NEXT_MAP,
        min=-1,
        max=3600,
    ),
    # --- bots -----------------------------------------------------------------------
    CuratedSetting(
        key="bot_number",
        group="bots",
        label="Bots",
        help="Minimum number of bots kept in the match.",
        kind="int",
        default=0,
        apply=ApplyClass.NOW,
        min=0,
        max=255,
    ),
    CuratedSetting(
        key="minplayers",
        group="bots",
        label="Fill to players",
        help="Add bots until this many players are in a teamless match.",
        kind="int",
        default=0,
        apply=ApplyClass.NOW,
        min=0,
        max=255,
    ),
    CuratedSetting(
        key="skill",
        group="bots",
        label="Bot skill",
        help="0 is the easiest, 10 the hardest.",
        kind="int",
        default=8,
        apply=ApplyClass.NOW,
        min=0,
        max=10,
    ),
    # --- voting ---------------------------------------------------------------------
    CuratedSetting(
        key="g_maplist_votable",
        group="voting",
        label="Maps in the vote",
        help="How many maps players choose between at the end of a match. 0 disables voting.",
        kind="int",
        default=6,
        apply=ApplyClass.NEXT_MAP,
        min=0,
        max=20,
        value_labels=((0, "Voting off"),),
    ),
    CuratedSetting(
        key="g_maplist_votable_timeout",
        group="voting",
        label="Vote length",
        help="Seconds the map vote lasts (the game requires less than 50).",
        kind="int",
        default=30,
        apply=ApplyClass.NEXT_MAP,
        min=1,
        max=49,
    ),
    # --- mutators -------------------------------------------------------------------
    _mutator("g_instagib", "Instagib", "Everyone has the one-shot vaporizer."),
    _mutator("g_nix", "NIX", "Everyone plays with the same weapon, which changes over time."),
    _mutator("g_vampire", "Vampire", "Damage dealt heals the attacker."),
    _mutator("g_jetpack", "Jetpack", "Everyone has a jetpack."),
    _mutator("g_pinata", "Pinata", "Players drop every weapon they carried when killed."),
    _mutator("g_midair", "Midair", "Players can only be damaged while airborne."),
    _mutator("g_touchexplode", "Touch explode", "Touching another player causes an explosion."),
    _mutator("g_cloaked", "Cloaked", "Every player is mostly invisible."),
    _mutator("g_walljump", "Wall jump", "Players can jump off walls."),
    _mutator("g_dodging", "Dodging", "Quick acceleration in a chosen direction."),
    _mutator("g_nades", "Grenades", "Off-hand grenades for everyone."),
    CuratedSetting(
        key="g_norecoil",
        group="mutators",
        label="No recoil",
        help="Shooting does not move the crosshair upwards.",
        kind="bool",
        default=True,
        apply=ApplyClass.NEXT_MAP,
    ),
    # --- server ---------------------------------------------------------------------
    CuratedSetting(
        key="sv_autopause",
        group="server",
        label="Pause when empty",
        help=(
            "Pause the game while nobody is connected and resume when a player joins. "
            "Keeps an idle server's CPU use near zero."
        ),
        kind="bool",
        default=True,
        apply=ApplyClass.NOW,
    ),
)

CURATED_BY_KEY: dict[str, CuratedSetting] = {s.key: s for s in CURATED}


@dataclass(frozen=True)
class Gametype:
    id: str  # as used by ``gametype <id>`` and in ``:gamestart:<id>_<map>``
    cvar: str  # ``g_<mode>``: 1 selects it
    name: str
    score_unit: str  # what the score limit counts


GAMETYPES: tuple[Gametype, ...] = (
    Gametype("dm", "g_dm", "Deathmatch", "frags"),
    Gametype("tdm", "g_tdm", "Team Deathmatch", "points"),
    Gametype("ctf", "g_ctf", "Capture the Flag", "captures"),
    Gametype("ca", "g_ca", "Clan Arena", "rounds"),
    Gametype("ft", "g_freezetag", "Freeze Tag", "rounds"),
    Gametype("kh", "g_keyhunt", "Key Hunt", "points"),
    Gametype("ka", "g_keepaway", "Keepaway", "points"),
    Gametype("tka", "g_tka", "Team Keepaway", "points"),
    Gametype("ons", "g_onslaught", "Onslaught", "points"),
    Gametype("as", "g_assault", "Assault", "points"),
    Gametype("dom", "g_domination", "Domination", "points"),
    Gametype("duel", "g_duel", "Duel", "frags"),
    Gametype("lms", "g_lms", "Last Man Standing", "lives"),
    Gametype("nb", "g_nexball", "Nexball", "goals"),
    Gametype("rc", "g_race", "Race", "laps"),
    Gametype("cts", "g_cts", "Complete the Stage", "points"),
    Gametype("inv", "g_invasion", "Invasion", "points"),
    Gametype("surv", "g_survival", "Survival", "rounds"),
    Gametype("mayhem", "g_mayhem", "Mayhem", "points"),
    Gametype("tmayhem", "g_tmayhem", "Team Mayhem", "points"),
)

GAMETYPES_BY_ID: dict[str, Gametype] = {g.id: g for g in GAMETYPES}
DEFAULT_GAMETYPE = "dm"
