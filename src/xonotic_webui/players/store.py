"""The persistent player history: a SQLite database under the state directory (design D5).

Everything is stored per match, so comparisons and time windows later are queries, not
migrations. ``player_totals`` is only a cache of the per-match sums for the players a write
touched, refreshed in the same transaction, so a list of tens of thousands of players is an
indexed read instead of an aggregation. The database is used from one worker thread,
serialised by construction, so no database call ever runs on the event loop.

Frags, deaths, suicides and team kills come only from the live ``:kill`` events; score,
damage, time playing, weapons and the rest come only from the end-of-match report. The
two sit side by side in ``match_players`` so they never double count.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from xonotic_webui.colors import strip_colors
from xonotic_webui.logging import get_logger

log = get_logger("players.store")

SCHEMA_VERSION = 2

T = TypeVar("T")

_SCHEMA_V1 = """
CREATE TABLE players (
    id          INTEGER PRIMARY KEY,
    key         TEXT NOT NULL UNIQUE,
    is_bot      INTEGER NOT NULL DEFAULT 0,
    name        TEXT NOT NULL,
    plain       TEXT NOT NULL DEFAULT '',
    first_seen  INTEGER NOT NULL,
    last_seen   INTEGER NOT NULL
);
CREATE TABLE aliases (
    player_id   INTEGER NOT NULL REFERENCES players(id),
    name        TEXT NOT NULL,
    plain       TEXT NOT NULL,
    first_used  INTEGER NOT NULL,
    last_used   INTEGER NOT NULL,
    PRIMARY KEY (player_id, name)
);
CREATE INDEX aliases_name ON aliases(name);
CREATE INDEX aliases_plain ON aliases(plain);
CREATE TABLE matches (
    id          INTEGER PRIMARY KEY,
    match_id    TEXT NOT NULL UNIQUE,
    map         TEXT NOT NULL DEFAULT '',
    gametype    TEXT NOT NULL DEFAULT '',
    started_at  INTEGER NOT NULL,
    duration    REAL,
    finished    INTEGER,
    reported    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE sessions (
    id          INTEGER PRIMARY KEY,
    player_id   INTEGER NOT NULL REFERENCES players(id),
    started_at  INTEGER NOT NULL,
    ended_at    INTEGER
);
CREATE INDEX sessions_player ON sessions(player_id);
CREATE TABLE match_players (
    match_pk    INTEGER NOT NULL REFERENCES matches(id),
    player_id   INTEGER NOT NULL REFERENCES players(id),
    frags       INTEGER NOT NULL DEFAULT 0,
    deaths      INTEGER NOT NULL DEFAULT 0,
    suicides    INTEGER NOT NULL DEFAULT 0,
    teamkills   INTEGER NOT NULL DEFAULT 0,
    score       REAL NOT NULL DEFAULT 0,
    kills       REAL NOT NULL DEFAULT 0,
    alivetime   REAL NOT NULL DEFAULT 0,
    dmg         REAL NOT NULL DEFAULT 0,
    dmgtaken    REAL NOT NULL DEFAULT 0,
    wins        INTEGER NOT NULL DEFAULT 0,
    rank        INTEGER,
    avglatency  REAL NOT NULL DEFAULT 0,
    scoreboard_valid INTEGER NOT NULL DEFAULT 0,
    joined      INTEGER NOT NULL DEFAULT 0,
    reported    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (match_pk, player_id)
);
CREATE INDEX match_players_player ON match_players(player_id);
CREATE TABLE weapon_stats (
    match_pk    INTEGER NOT NULL,
    player_id   INTEGER NOT NULL,
    weapon      TEXT NOT NULL,
    frags       REAL NOT NULL DEFAULT 0,
    hit         REAL NOT NULL DEFAULT 0,
    fired       REAL NOT NULL DEFAULT 0,
    cnt_hit     REAL NOT NULL DEFAULT 0,
    cnt_fired   REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (match_pk, player_id, weapon)
);
CREATE INDEX weapon_stats_player ON weapon_stats(player_id);
CREATE TABLE achievements (
    match_pk    INTEGER NOT NULL,
    player_id   INTEGER NOT NULL,
    name        TEXT NOT NULL,
    count       INTEGER NOT NULL,
    PRIMARY KEY (match_pk, player_id, name)
);
CREATE INDEX achievements_player ON achievements(player_id);
CREATE TABLE extra_stats (
    match_pk    INTEGER NOT NULL,
    player_id   INTEGER NOT NULL,
    name        TEXT NOT NULL,
    value       REAL NOT NULL,
    PRIMARY KEY (match_pk, player_id, name)
);
CREATE INDEX extra_stats_player ON extra_stats(player_id);
CREATE INDEX sessions_open ON sessions(player_id) WHERE ended_at IS NULL;
CREATE TABLE player_totals (
    player_id       INTEGER PRIMARY KEY REFERENCES players(id),
    frags           INTEGER NOT NULL DEFAULT 0,
    deaths          INTEGER NOT NULL DEFAULT 0,
    suicides        INTEGER NOT NULL DEFAULT 0,
    teamkills       INTEGER NOT NULL DEFAULT 0,
    score           REAL NOT NULL DEFAULT 0,
    wins            INTEGER NOT NULL DEFAULT 0,
    matches         INTEGER NOT NULL DEFAULT 0,
    time_playing    REAL NOT NULL DEFAULT 0,
    dmg             REAL NOT NULL DEFAULT 0,
    dmgtaken        REAL NOT NULL DEFAULT 0,
    avg_latency     REAL,
    hit             REAL NOT NULL DEFAULT 0,
    fired           REAL NOT NULL DEFAULT 0,
    closed_seconds  INTEGER NOT NULL DEFAULT 0,
    kd              REAL NOT NULL DEFAULT 0,
    accuracy        REAL
);
"""

# The per-map totals group the match history by map name.
_SCHEMA_V2 = """
CREATE INDEX matches_map ON matches(map);
"""

# Forward-only migrations: ``_MIGRATIONS[n]`` takes the database from version n to n + 1.
_MIGRATIONS: dict[int, str] = {0: _SCHEMA_V1, 1: _SCHEMA_V2}

# The gametype shown for matches that were recorded without one.
UNKNOWN_GAMETYPE = "unknown"

# How many players the per-map details list.
MAP_TOP_FRAGGERS = 10

# Columns the list can be sorted by. The values are SQL expressions over the list query's
# aliases; they are never taken from input.
SORT_COLUMNS: dict[str, str] = {
    "name": "p.plain",
    "frags": "frags",
    "deaths": "deaths",
    "kd": "kd",
    "score": "score",
    "wins": "wins",
    "matches": "matches",
    "time_playing": "time_playing",
    "time_on_server": "time_on_server",
    "accuracy": "accuracy",
    "last_seen": "p.last_seen",
}

# Scoreboard labels the schema has columns for (or that carry no information).
_KNOWN_LABELS = frozenset(
    {"score", "kills", "deaths", "suicides", "teamkills", "dmg", "dmgtaken", "elo"}
)


class PlayerStoreError(RuntimeError):
    """The player database cannot be used."""


class SchemaTooNewError(PlayerStoreError):
    """The database was written by a newer panel."""


@dataclass(frozen=True)
class ReportedPlayer:
    """What one report says about one player, ready to store (see ``Ops.apply_report``)."""

    score: float = 0.0
    kills: float = 0.0
    alivetime: float = 0.0
    dmg: float = 0.0
    dmgtaken: float = 0.0
    wins: int = 0
    rank: int | None = None
    avglatency: float = 0.0
    scoreboard_valid: bool = False
    joined: int = 0
    weapons: dict[str, dict[str, float]] | None = None
    achievements: dict[str, int] | None = None
    extra: dict[str, float] | None = None


def like_escape(text: str) -> str:
    """Escape ``%``, ``_`` and the escape character for ``LIKE ... ESCAPE '\\'``."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def plain_key(name: str) -> str:
    """The form names are matched in: colour codes removed, case folded."""
    return strip_colors(name).casefold()


class Ops:
    """The database operations. Instances only exist inside a store transaction."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    # -- the totals cache ------------------------------------------------------------
    def refresh_totals(self, player_ids: Iterable[int]) -> None:
        """Recompute the cached totals of ``player_ids`` from their per-match rows."""
        for pid in set(player_ids):
            self._c.execute("INSERT OR IGNORE INTO player_totals(player_id) VALUES(?)", (pid,))
            self._c.execute(
                """
                UPDATE player_totals SET
                  frags = (SELECT COALESCE(SUM(frags), 0) FROM match_players WHERE player_id = ?1),
                  deaths = (SELECT COALESCE(SUM(deaths), 0) FROM match_players
                            WHERE player_id = ?1),
                  suicides = (SELECT COALESCE(SUM(suicides), 0) FROM match_players
                              WHERE player_id = ?1),
                  teamkills = (SELECT COALESCE(SUM(teamkills), 0) FROM match_players
                               WHERE player_id = ?1),
                  score = (SELECT COALESCE(SUM(score), 0) FROM match_players WHERE player_id = ?1),
                  wins = (SELECT COALESCE(SUM(wins), 0) FROM match_players WHERE player_id = ?1),
                  matches = (SELECT COUNT(*) FROM match_players mp JOIN matches m
                             ON m.id = mp.match_pk
                             WHERE mp.player_id = ?1 AND m.finished = 1
                               AND mp.scoreboard_valid = 1),
                  time_playing = (SELECT COALESCE(SUM(alivetime), 0) FROM match_players
                                  WHERE player_id = ?1),
                  dmg = (SELECT COALESCE(SUM(dmg), 0) FROM match_players WHERE player_id = ?1),
                  dmgtaken = (SELECT COALESCE(SUM(dmgtaken), 0) FROM match_players
                              WHERE player_id = ?1),
                  avg_latency = (SELECT AVG(avglatency) FROM match_players
                                 WHERE player_id = ?1 AND avglatency > 0),
                  hit = (SELECT COALESCE(SUM(hit), 0) FROM weapon_stats WHERE player_id = ?1),
                  fired = (SELECT COALESCE(SUM(fired), 0) FROM weapon_stats WHERE player_id = ?1),
                  closed_seconds = (SELECT COALESCE(SUM(ended_at - started_at), 0) FROM sessions
                                    WHERE player_id = ?1 AND ended_at IS NOT NULL)
                WHERE player_id = ?1
                """,
                (pid,),
            )
            self._c.execute(
                "UPDATE player_totals SET kd = CAST(frags AS REAL) / MAX(deaths, 1), "
                "accuracy = CASE WHEN fired > 0 THEN hit / fired END WHERE player_id = ?",
                (pid,),
            )

    # -- players and names -------------------------------------------------------------
    def get_or_create_player(self, key: str, name: str, *, is_bot: bool, now: int) -> int:
        row = self._c.execute("SELECT id FROM players WHERE key = ?", (key,)).fetchone()
        if row is not None:
            player_id = int(row[0])
            self._c.execute(
                "UPDATE players SET last_seen = MAX(last_seen, ?) WHERE id = ?", (now, player_id)
            )
        else:
            cur = self._c.execute(
                "INSERT INTO players(key, is_bot, name, plain, first_seen, last_seen) "
                "VALUES(?,?,?,?,?,?)",
                (key, 1 if is_bot else 0, name, plain_key(name), now, now),
            )
            player_id = int(cur.lastrowid or 0)
            self._c.execute("INSERT INTO player_totals(player_id) VALUES(?)", (player_id,))
        self.upsert_alias(player_id, name, now)
        return player_id

    def touch_player(self, player_id: int, now: int) -> None:
        self._c.execute(
            "UPDATE players SET last_seen = MAX(last_seen, ?) WHERE id = ?", (now, player_id)
        )

    def upsert_alias(self, player_id: int, name: str, now: int) -> None:
        """Record a name as used now; it becomes the player's shown name."""
        if not name:
            return
        self._c.execute(
            "INSERT INTO aliases(player_id, name, plain, first_used, last_used) "
            "VALUES(?,?,?,?,?) "
            "ON CONFLICT(player_id, name) DO UPDATE SET "
            "last_used = MAX(last_used, excluded.last_used)",
            (player_id, name, plain_key(name), now, now),
        )
        # The shown name is the most recently used one; a name noted late (older than one
        # already recorded) does not replace it.
        self._c.execute(
            "UPDATE players SET name = ?, plain = ? WHERE id = ? AND NOT EXISTS ("
            "SELECT 1 FROM aliases WHERE player_id = ? AND name != ? AND last_used > ?)",
            (name, plain_key(name), player_id, player_id, name, now),
        )

    # -- sessions ----------------------------------------------------------------------
    def open_session(self, player_id: int, started_at: int) -> int:
        cur = self._c.execute(
            "INSERT INTO sessions(player_id, started_at) VALUES(?, ?)", (player_id, started_at)
        )
        return int(cur.lastrowid or 0)

    def close_session(self, session_id: int, ended_at: int) -> None:
        row = self._c.execute(
            "SELECT player_id FROM sessions WHERE id = ? AND ended_at IS NULL", (session_id,)
        ).fetchone()
        if row is None:
            return
        self._c.execute(
            "UPDATE sessions SET ended_at = MAX(started_at, ?) WHERE id = ?",
            (ended_at, session_id),
        )
        self.refresh_totals([int(row[0])])

    def close_stale_sessions(self) -> int:
        """Close sessions left open by a panel that did not shut down, at ``last_seen``."""
        affected = [
            int(r[0])
            for r in self._c.execute(
                "SELECT DISTINCT player_id FROM sessions WHERE ended_at IS NULL"
            )
        ]
        cur = self._c.execute(
            "UPDATE sessions SET ended_at = MAX(started_at, "
            "(SELECT last_seen FROM players WHERE players.id = sessions.player_id)) "
            "WHERE ended_at IS NULL"
        )
        self.refresh_totals(affected)
        return cur.rowcount

    # -- matches -------------------------------------------------------------------------
    def upsert_match(self, match_id: str, map_name: str, gametype: str, started_at: int) -> int:
        self._c.execute(
            "INSERT INTO matches(match_id, map, gametype, started_at) VALUES(?,?,?,?) "
            "ON CONFLICT(match_id) DO UPDATE SET "
            "map = CASE WHEN matches.map = '' THEN excluded.map ELSE matches.map END, "
            "gametype = CASE WHEN matches.gametype = '' THEN excluded.gametype "
            "ELSE matches.gametype END",
            (match_id, map_name, gametype, started_at),
        )
        row = self._c.execute("SELECT id FROM matches WHERE match_id = ?", (match_id,)).fetchone()
        return int(row[0])

    def add_counters(
        self,
        match_pk: int,
        player_id: int,
        *,
        frags: int = 0,
        deaths: int = 0,
        suicides: int = 0,
        teamkills: int = 0,
    ) -> None:
        self._c.execute(
            "INSERT INTO match_players(match_pk, player_id, frags, deaths, suicides, teamkills) "
            "VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(match_pk, player_id) DO UPDATE SET "
            "frags = frags + excluded.frags, deaths = deaths + excluded.deaths, "
            "suicides = suicides + excluded.suicides, teamkills = teamkills + excluded.teamkills",
            (match_pk, player_id, frags, deaths, suicides, teamkills),
        )
        self.refresh_totals([player_id])

    def apply_report(
        self,
        match_pk: int,
        *,
        finished: bool,
        duration: float,
        players: Iterable[tuple[int, ReportedPlayer]],
    ) -> None:
        """Store a report's figures. Applying the same report again changes nothing."""
        self._c.execute(
            "UPDATE matches SET finished = ?, duration = ?, reported = 1 WHERE id = ?",
            (1 if finished else 0, duration, match_pk),
        )
        touched: list[int] = [
            int(r[0])
            for r in self._c.execute(
                "SELECT player_id FROM match_players WHERE match_pk = ?", (match_pk,)
            )
        ]  # the match's finished flag changes what every participant's totals say
        for player_id, p in players:
            touched.append(player_id)
            self._c.execute(
                "INSERT INTO match_players(match_pk, player_id, score, kills, alivetime, dmg, "
                "dmgtaken, wins, rank, avglatency, scoreboard_valid, joined, reported) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1) "
                "ON CONFLICT(match_pk, player_id) DO UPDATE SET score = excluded.score, "
                "kills = excluded.kills, alivetime = excluded.alivetime, dmg = excluded.dmg, "
                "dmgtaken = excluded.dmgtaken, wins = excluded.wins, rank = excluded.rank, "
                "avglatency = excluded.avglatency, "
                "scoreboard_valid = excluded.scoreboard_valid, joined = excluded.joined, "
                "reported = 1",
                (
                    match_pk,
                    player_id,
                    p.score,
                    p.kills,
                    p.alivetime,
                    p.dmg,
                    p.dmgtaken,
                    p.wins,
                    p.rank,
                    p.avglatency,
                    1 if p.scoreboard_valid else 0,
                    p.joined,
                ),
            )
            for table in ("weapon_stats", "achievements", "extra_stats"):
                self._c.execute(
                    f"DELETE FROM {table} WHERE match_pk = ? AND player_id = ?",
                    (match_pk, player_id),
                )
            for weapon, w in (p.weapons or {}).items():
                self._c.execute(
                    "INSERT INTO weapon_stats(match_pk, player_id, weapon, frags, hit, fired, "
                    "cnt_hit, cnt_fired) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        match_pk,
                        player_id,
                        weapon,
                        w.get("frags", 0.0),
                        w.get("hit", 0.0),
                        w.get("fired", 0.0),
                        w.get("cnt-hit", 0.0),
                        w.get("cnt-fired", 0.0),
                    ),
                )
            for name, count in (p.achievements or {}).items():
                self._c.execute(
                    "INSERT INTO achievements(match_pk, player_id, name, count) VALUES(?,?,?,?)",
                    (match_pk, player_id, name, count),
                )
            for name, value in (p.extra or {}).items():
                self._c.execute(
                    "INSERT INTO extra_stats(match_pk, player_id, name, value) VALUES(?,?,?,?)",
                    (match_pk, player_id, name, value),
                )
        self.refresh_totals(touched)

    # -- reading -------------------------------------------------------------------------
    def list_players(
        self,
        *,
        sort: str,
        descending: bool,
        query: str | None,
        bots: bool,
        limit: int,
        offset: int,
        now: int,
    ) -> tuple[int, list[dict[str, Any]]]:
        order = SORT_COLUMNS[sort]  # a KeyError here is a caller bug, never input
        direction = "DESC" if descending else "ASC"
        where = ["1 = 1"]
        args: list[Any] = [now]
        if not bots:
            where.append("p.is_bot = 0")
        if query:
            where.append(
                "EXISTS (SELECT 1 FROM aliases a WHERE a.player_id = p.id "
                "AND a.plain LIKE ? ESCAPE '\\')"
            )
            args.append("%" + like_escape(plain_key(query)) + "%")
        where_sql = " AND ".join(where)
        total = self._c.execute(
            f"SELECT COUNT(*) FROM players p WHERE {where_sql}",
            args[1:],
        ).fetchone()[0]
        nulls = "(accuracy IS NULL) ASC, " if sort == "accuracy" else ""
        rows = self._c.execute(
            f"{_LIST_SELECT} WHERE {where_sql} "
            f"ORDER BY {nulls}{order} {direction}, p.id ASC LIMIT ? OFFSET ?",
            [*args, limit, offset],
        ).fetchall()
        return int(total), [_row_dict(r) for r in rows]

    def get_player(self, player_id: int, *, now: int) -> dict[str, Any] | None:
        row = self._c.execute(
            f"{_LIST_SELECT} WHERE p.id = ?",
            [now, player_id],
        ).fetchone()
        if row is None:
            return None
        player = _row_dict(row)
        key_row = self._c.execute("SELECT key FROM players WHERE id = ?", (player_id,)).fetchone()
        key = str(key_row[0])
        player["key"] = key
        player["aliases"] = [
            {"name": r[0], "first_used": r[1], "last_used": r[2]}
            for r in self._c.execute(
                "SELECT name, first_used, last_used FROM aliases WHERE player_id = ? "
                "ORDER BY last_used DESC, name",
                (player_id,),
            )
        ]
        player["sessions"] = self._c.execute(
            "SELECT COUNT(*) FROM sessions WHERE player_id = ?", (player_id,)
        ).fetchone()[0]
        player["weapons"] = [
            {
                "weapon": r[0],
                "frags": r[1],
                "hit": r[2],
                "fired": r[3],
                "cnt_hit": r[4],
                "cnt_fired": r[5],
            }
            for r in self._c.execute(
                "SELECT weapon, SUM(frags), SUM(hit), SUM(fired), SUM(cnt_hit), SUM(cnt_fired) "
                "FROM weapon_stats WHERE player_id = ? GROUP BY weapon "
                "ORDER BY SUM(frags) DESC, SUM(fired) DESC, weapon",
                (player_id,),
            )
        ]
        player["achievements"] = [
            {"name": r[0], "count": r[1]}
            for r in self._c.execute(
                "SELECT name, SUM(count) FROM achievements WHERE player_id = ? GROUP BY name "
                "ORDER BY name",
                (player_id,),
            )
        ]
        player["extra"] = [
            {"name": r[0], "value": r[1]}
            for r in self._c.execute(
                "SELECT name, SUM(value) FROM extra_stats WHERE player_id = ? GROUP BY name "
                "ORDER BY name",
                (player_id,),
            )
        ]
        player["has_match_stats"] = bool(
            self._c.execute(
                "SELECT 1 FROM match_players WHERE player_id = ? AND reported = 1 LIMIT 1",
                (player_id,),
            ).fetchone()
        )
        return player

    def map_totals(self) -> dict[str, tuple[int, int, int | None]]:
        """``{map: (played, frags, last_played)}`` for every map with a recorded participant.

        A match counts as played when it finished and has a participant; frags come from every
        match on the map; the last played time is the latest start of any match that has a
        participant (design D1).
        """
        rows = self._c.execute(
            """
            SELECT m.map,
                   SUM(CASE WHEN m.finished = 1 THEN 1 ELSE 0 END),
                   SUM(s.frags),
                   MAX(m.started_at)
            FROM matches m
            JOIN (SELECT match_pk, SUM(frags) AS frags FROM match_players GROUP BY match_pk) s
              ON s.match_pk = m.id
            GROUP BY m.map
            """
        )
        return {str(r[0]): (int(r[1]), int(r[2]), int(r[3])) for r in rows}

    def map_detail(self, name: str) -> dict[str, Any]:
        """The play details of one map (design D1); zeros and empty lists when never played."""
        played, cut_short, frags, first, last = self._c.execute(
            """
            SELECT COALESCE(SUM(CASE WHEN m.finished = 1 THEN 1 ELSE 0 END), 0),
                   COALESCE(SUM(CASE WHEN m.finished = 0 THEN 1 ELSE 0 END), 0),
                   COALESCE(SUM(s.frags), 0),
                   MIN(m.started_at),
                   MAX(m.started_at)
            FROM matches m
            JOIN (
                SELECT mp.match_pk, SUM(mp.frags) AS frags
                FROM match_players mp
                WHERE mp.match_pk IN (SELECT id FROM matches WHERE map = ?)
                GROUP BY mp.match_pk
            ) s ON s.match_pk = m.id
            """,
            (name,),
        ).fetchone()
        gametypes = [
            {"gametype": r[0] or UNKNOWN_GAMETYPE, "played": int(r[1])}
            for r in self._c.execute(
                """
                SELECT m.gametype, COUNT(*) AS n
                FROM matches m
                WHERE m.map = ? AND m.finished = 1
                  AND EXISTS (SELECT 1 FROM match_players mp WHERE mp.match_pk = m.id)
                GROUP BY m.gametype
                ORDER BY n DESC, COALESCE(NULLIF(m.gametype, ''), ?)
                """,
                (name, UNKNOWN_GAMETYPE),
            )
        ]
        top = [
            {"player_id": int(r[0]), "name": r[1], "frags": int(r[2]), "is_bot": bool(r[3])}
            for r in self._c.execute(
                """
                SELECT p.id, p.name, SUM(mp.frags) AS f, p.is_bot
                FROM match_players mp
                JOIN matches m ON m.id = mp.match_pk
                JOIN players p ON p.id = mp.player_id
                WHERE m.map = ?
                GROUP BY p.id
                ORDER BY f DESC, p.plain, p.id
                LIMIT ?
                """,
                (name, MAP_TOP_FRAGGERS),
            )
        ]
        return {
            "played": int(played),
            "cut_short": int(cut_short),
            "frags": int(frags),
            "first_played": None if first is None else int(first),
            "last_played": None if last is None else int(last),
            "gametypes": gametypes,
            "top_fraggers": top,
        }


# The list query: the cached totals joined to players. An open session counts up to ``?1``
# (the first parameter).
_LIST_SELECT = """
SELECT p.id, p.name, p.is_bot, p.first_seen, p.last_seen,
       t.frags AS frags, t.deaths AS deaths, t.suicides AS suicides, t.teamkills AS teamkills,
       t.score AS score, t.wins AS wins, t.matches AS matches, t.time_playing AS time_playing,
       t.closed_seconds + COALESCE(o.open_seconds, 0) AS time_on_server,
       t.dmg AS dmg, t.dmgtaken AS dmgtaken, t.avg_latency AS avg_latency,
       t.kd AS kd, t.accuracy AS accuracy
FROM players p
JOIN player_totals t ON t.player_id = p.id
LEFT JOIN (
    SELECT player_id, SUM(MAX(0, ?1 - started_at)) AS open_seconds
    FROM sessions WHERE ended_at IS NULL GROUP BY player_id
) o ON o.player_id = p.id
""".replace("?1", "?")


def _row_dict(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    r = list(row)
    return {
        "id": r[0],
        "name": r[1],
        "is_bot": bool(r[2]),
        "first_seen": r[3],
        "last_seen": r[4],
        "frags": int(r[5]),
        "deaths": int(r[6]),
        "suicides": int(r[7]),
        "teamkills": int(r[8]),
        "score": r[9],
        "wins": int(r[10]),
        "matches": int(r[11]),
        "time_playing": r[12],
        "time_on_server": r[13],
        "dmg": r[14],
        "dmgtaken": r[15],
        "avg_latency": r[16],
        "kd": r[17],
        "accuracy": r[18],
    }


def extra_labels(scoreboard_values: dict[str, float]) -> dict[str, float]:
    """The scoreboard labels with no column of their own (gametype specific ones)."""
    return {k: v for k, v in scoreboard_values.items() if k not in _KNOWN_LABELS and v}


class PlayerStore:
    """The async face of the database.

    ``transact`` runs a function with an :class:`Ops` in one transaction on the store's
    single worker thread, and returns its result.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._executor: ThreadPoolExecutor | None = None
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()
        self.revision = 0  # bumped by every committed write; the API's ETag uses it

    # -- lifecycle -------------------------------------------------------------------
    async def open(self) -> None:
        if self._conn is not None:
            return
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="players-db")
        try:
            await self._run(self._connect)
        except Exception:
            self._executor.shutdown(wait=False)
            self._executor = None
            raise

    def _connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA foreign_keys = ON")
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise SchemaTooNewError(
                    f"{self.path} has schema version {version}, newer than this panel's "
                    f"{SCHEMA_VERSION}; upgrade the panel or move the file away"
                )
            while version < SCHEMA_VERSION:
                conn.execute("BEGIN")
                try:
                    for statement in _split(_MIGRATIONS[version]):
                        conn.execute(statement)
                    version += 1
                    conn.execute(f"PRAGMA user_version = {version}")
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
        except Exception:
            conn.close()
            raise
        self._conn = conn

    async def close(self) -> None:
        if self._executor is None:
            return
        try:
            await self._run(self._disconnect)
        finally:
            self._executor.shutdown(wait=True)
            self._executor = None

    def _disconnect(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def is_open(self) -> bool:
        return self._conn is not None

    # -- running ---------------------------------------------------------------------
    async def _run(self, fn: Callable[..., T], *args: Any) -> T:
        executor = self._executor
        if executor is None:
            raise PlayerStoreError("the player database is not open")
        loop = asyncio.get_running_loop()
        async with self._lock:
            return await loop.run_in_executor(executor, fn, *args)

    async def transact(self, fn: Callable[[Ops], T], *, write: bool = True) -> T:
        """Run ``fn`` in one transaction. A write bumps :attr:`revision` once committed."""

        def work() -> T:
            conn = self._conn
            if conn is None:
                raise PlayerStoreError("the player database is not open")
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                result = fn(Ops(conn))
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
            return result

        result = await self._run(work)
        if write:
            self.revision += 1
        return result

    # -- convenience ---------------------------------------------------------------
    async def list_players(
        self,
        *,
        sort: str = "frags",
        descending: bool = True,
        query: str | None = None,
        bots: bool = False,
        limit: int = 50,
        offset: int = 0,
        now: int | None = None,
    ) -> tuple[int, list[dict[str, Any]]]:
        moment = int(time.time()) if now is None else now
        return await self.transact(
            lambda ops: ops.list_players(
                sort=sort,
                descending=descending,
                query=query,
                bots=bots,
                limit=limit,
                offset=offset,
                now=moment,
            ),
            write=False,
        )

    async def get_player(self, player_id: int, *, now: int | None = None) -> dict[str, Any] | None:
        moment = int(time.time()) if now is None else now
        return await self.transact(lambda ops: ops.get_player(player_id, now=moment), write=False)

    async def map_totals(self) -> dict[str, tuple[int, int, int | None]]:
        return await self.transact(lambda ops: ops.map_totals(), write=False)

    async def map_detail(self, name: str) -> dict[str, Any]:
        return await self.transact(lambda ops: ops.map_detail(name), write=False)


def _split(script: str) -> list[str]:
    return [s.strip() for s in script.split(";") if s.strip()]
