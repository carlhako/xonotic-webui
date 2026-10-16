"""Turns the server's console output into persistent player history (player-stats spec).

A second consumer of the supervisor's line flow, beside the status tracker (design D1). It
follows joins, parts, renames, kills and the end-of-match report, keeps what it learns in
memory, and a flush task writes it to the store (D4). Nothing here can stop the game server
or the event loop: store work runs on the store's worker thread, and every failure is
logged and retried at the next flush.

Identity (D2): a human is keyed by the key fingerprint ``sv_cmd who`` reports for their
slot, else by their colour-stripped name; bots by their name. Sessions (D3) belong to a slot
and survive a map change when the same key re-joins it.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from xonotic_webui.colors import strip_colors
from xonotic_webui.console.console import Console, InternalQueryError
from xonotic_webui.events import (
    GameStart,
    PlayerJoin,
    PlayerKill,
    PlayerName,
    PlayerPart,
    parse_event,
)
from xonotic_webui.logging import get_logger
from xonotic_webui.players.report import (
    Report,
    ReportParser,
    ReportPlayer,
    achievements,
    scoreboard,
    weapon_stats,
)
from xonotic_webui.players.store import Ops, PlayerStore, ReportedPlayer, extra_labels
from xonotic_webui.players.who import WhoReplyCollector
from xonotic_webui.supervisor import NotRunningError, RunState, Supervisor, SupervisorError

log = get_logger("players")

WHO_COMMAND = 'sv_cmd who "|"'

# An open session's player is marked as seen at least this often, which bounds how much a
# panel crash can add or lose (D3). It is not tied to the flush interval so an idle server
# full of bots does not write every few seconds.
_TOUCH_INTERVAL = 30


@dataclass(eq=False)
class _Match:
    match_id: str | None  # ``None`` until known (the panel started mid-match)
    map: str = ""
    gametype: str = ""
    started_at: int = 0
    participants: dict[int, _Participant] = field(default_factory=dict)
    pk: int | None = None
    superseded_at: float | None = None
    reported: bool = False


@dataclass(eq=False)
class _Session:
    ent: int
    key: str
    started_at: int
    participant: _Participant | None = None
    ended_at: int | None = None
    awaiting_since: float | None = None  # set at a map change until the slot re-joins
    pk: int | None = None
    end_written: bool = False
    last_touch: int = 0


@dataclass(eq=False)
class _Participant:
    match: _Match
    pid: int
    ent: int
    name: str
    bot: bool
    joined_at: int
    key: str | None = None
    db_id: int | None = None
    names: list[str] = field(default_factory=list)  # not yet written as aliases
    frags: int = 0  # live counters not yet written
    deaths: int = 0
    suicides: int = 0
    teamkills: int = 0
    session: _Session | None = None
    left_at: int | None = None

    @property
    def dirty(self) -> bool:
        return bool(self.frags or self.deaths or self.suicides or self.teamkills or self.names)


@dataclass(eq=False)
class _PendingReport:
    match: _Match
    report: Report
    players: list[tuple[_Participant, ReportedPlayer]]


# -- a flush's plan: plain snapshots, handed to the store's thread ---------------------------


@dataclass(frozen=True)
class _PlanPlayer:
    ref: int
    key: str
    is_bot: bool
    db_id: int | None
    names: tuple[str, ...]
    fallback_name: str


@dataclass(frozen=True)
class _PlanMatch:
    ref: int
    match_id: str
    map: str
    gametype: str
    started_at: int
    pk: int | None


@dataclass(frozen=True)
class _PlanSession:
    ref: int
    player_ref: int
    player_db_id: int | None
    started_at: int
    pk: int | None
    ended_at: int | None
    end_written: bool


@dataclass(frozen=True)
class _PlanCounter:
    player_ref: int
    player_db_id: int | None
    match_ref: int
    deltas: tuple[int, int, int, int]  # frags, deaths, suicides, teamkills
    name: str  # the name the participant has now (match-history D8)


@dataclass(frozen=True)
class _PlanReport:
    ref: int
    match_ref: int
    finished: bool
    duration: float
    rows: tuple[tuple[int, int | None, ReportedPlayer], ...]  # player ref, known db id, figures
    teams: dict[int, dict[str, float]]  # each team's scoreboard values


@dataclass
class _Plan:
    now: int
    players: list[_PlanPlayer] = field(default_factory=list)
    matches: list[_PlanMatch] = field(default_factory=list)
    sessions: list[_PlanSession] = field(default_factory=list)
    counters: list[_PlanCounter] = field(default_factory=list)
    reports: list[_PlanReport] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.players or self.sessions or self.counters or self.reports)


@dataclass
class _Result:
    db_ids: dict[int, int] = field(default_factory=dict)  # participant ref -> players.id
    match_pks: dict[int, int] = field(default_factory=dict)  # match ref -> matches.id
    session_pks: dict[int, int] = field(default_factory=dict)  # session ref -> sessions.id
    counters_written: set[int] = field(default_factory=set)  # indexes into the plan
    reports_written: set[int] = field(default_factory=set)  # report refs
    sessions_closed: set[int] = field(default_factory=set)  # session refs


def name_key(name: str) -> str:
    """The identity of a player with no key fingerprint: the plain name, case folded."""
    return "name:" + strip_colors(name).strip().casefold()


def bot_key(name: str) -> str:
    return "bot:" + strip_colors(name).strip().casefold()


class PlayerRecorder:
    def __init__(
        self,
        supervisor: Supervisor,
        console: Console,
        store: PlayerStore,
        *,
        clock: Callable[[], float] = time.time,
        flush_interval: float = 2.0,
        lookup_delay: float = 0.1,
        lookup_timeout: float = 5.0,
        rejoin_grace: float = 120.0,
    ) -> None:
        self._sup = supervisor
        self._console = console
        self._store = store
        self._clock = clock
        self._flush_interval = flush_interval
        self._lookup_delay = lookup_delay
        self._lookup_timeout = lookup_timeout
        self._grace = rejoin_grace

        self._match: _Match | None = None
        self._retired: list[_Match] = []  # older matches that still have data to write
        self._sessions: dict[int, _Session] = {}  # open sessions by slot
        self._closed: list[_Session] = []  # ended sessions not yet fully written
        self._pending_reports: list[_PendingReport] = []
        self._lookup_queue: list[_Participant] = []
        self._lookup_task: asyncio.Task[None] | None = None
        self._reports = ReportParser()
        self._seen_report: Report | None = None

        self._flush_task: asyncio.Task[None] | None = None
        self._flush_requested = asyncio.Event()
        self._flush_lock = asyncio.Lock()
        self._running = False
        self.enabled = False  # set by start() once the store is open

        supervisor.add_line_sink(self.on_line)
        supervisor.subscribe_state(self._on_state)

    # -- lifecycle ---------------------------------------------------------------------
    async def start(self) -> None:
        """Open the store and start flushing.

        A store that cannot be opened is logged and leaves recording off; the rest of the
        panel is unaffected.
        """
        try:
            await self._store.open()
            await self._store.transact(lambda ops: ops.close_stale_sessions())
        except Exception:
            log.exception("the player database could not be opened; player history is off")
            self.enabled = False
            return
        self.enabled = True
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop(), name="players-flush")

    async def aclose(self) -> None:
        self._running = False
        for task in (self._lookup_task, self._flush_task):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self._flush_task = None
        self._lookup_task = None
        if self.enabled:
            # Anyone still counted as connected is not, now that the panel is going.
            self._close_all_sessions(int(self._clock()))
            await self.flush()
            with contextlib.suppress(Exception):
                await self._store.close()
        self.enabled = False

    @property
    def store(self) -> PlayerStore:
        return self._store

    @property
    def current_match_id(self) -> str | None:
        """The game's id of the match being played, or ``None`` when there is none (the
        server is not running, or the panel has not learnt the id yet)."""
        return self._match.match_id if self._match is not None else None

    # -- the line flow -----------------------------------------------------------------
    def on_line(self, raw_line: str) -> None:
        if not self.enabled:
            return
        try:
            self._consume(raw_line)
        except Exception:
            log.exception("player recorder failed on a line; continuing")

    def _consume(self, raw_line: str) -> None:
        consumed = self._reports.feed(raw_line)
        report = self._reports.report
        if report is not None and report is not self._seen_report:
            self._seen_report = report
            self._apply_report(report)
        if consumed:
            return
        event = parse_event(raw_line)
        if event is None:
            return
        now = int(self._clock())
        if isinstance(event, GameStart):
            self._on_gamestart(event, now)
        elif isinstance(event, PlayerJoin):
            self._on_join(event, now)
        elif isinstance(event, PlayerName):
            self._on_name(event)
        elif isinstance(event, PlayerPart):
            self._on_part(event, now)
        elif isinstance(event, PlayerKill):
            self._on_kill(event)

    # -- events --------------------------------------------------------------------------
    def _ensure_match(self, now: int) -> _Match:
        if self._match is None:
            self._match = _Match(match_id=None, started_at=now)
        return self._match

    def _retire_current(self, now: float) -> None:
        match = self._match
        self._match = None
        if match is not None and (match.participants or match.pk is not None):
            match.superseded_at = now
            self._retired.append(match)

    def _on_gamestart(self, event: GameStart, now: int) -> None:
        self._retire_current(float(now))
        self._match = _Match(
            match_id=event.match_id or None,
            map=event.map,
            gametype=event.gametype,
            started_at=now,
        )
        # Every connected client re-joins on a map change: wait for that before ending
        # their sessions (D3).
        for session in self._sessions.values():
            if session.awaiting_since is None:
                session.awaiting_since = float(now)
        self.request_flush()

    def _on_join(self, event: PlayerJoin, now: int) -> None:
        match = self._ensure_match(now)
        participant = _Participant(
            match=match,
            pid=event.player_id,
            ent=event.ent,
            name=event.name,
            bot=event.bot,
            joined_at=now,
            names=[event.name],
        )
        match.participants[event.player_id] = participant
        if event.bot:
            self._resolve(participant, bot_key(event.name))
        else:
            self._queue_lookup(participant)

    def _on_name(self, event: PlayerName) -> None:
        participant = self._participant(event.player_id)
        if participant is None or participant.name == event.name:
            return
        participant.name = event.name
        participant.names.append(event.name)

    def _on_part(self, event: PlayerPart, now: int) -> None:
        participant = self._participant(event.player_id)
        if participant is None:
            return
        participant.left_at = now
        session = participant.session
        if session is not None and session.ended_at is None and session.participant is participant:
            self._end_session(session, now)

    def _on_kill(self, event: PlayerKill) -> None:
        victim = self._participant(event.victim_id)
        killer = self._participant(event.killer_id)
        if event.mode == "frag" and killer is not None:
            killer.frags += 1
        elif event.mode == "tk" and killer is not None:
            killer.teamkills += 1
        elif event.mode == "suicide" and victim is not None:
            victim.suicides += 1
        if victim is not None:
            victim.deaths += 1

    def _participant(self, player_id: int) -> _Participant | None:
        return self._match.participants.get(player_id) if self._match is not None else None

    # -- identity (D2) --------------------------------------------------------------------
    def _queue_lookup(self, participant: _Participant) -> None:
        self._lookup_queue.append(participant)
        if self._lookup_task is None or self._lookup_task.done():
            self._lookup_task = asyncio.create_task(self._lookup_loop(), name="players-lookup")

    async def _lookup_loop(self) -> None:
        try:
            while self._lookup_queue:
                await asyncio.sleep(self._lookup_delay)  # let a burst of joins land first
                batch, self._lookup_queue = self._lookup_queue, []
                await self._lookup(batch)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("player lookup failed; identifying by name")
            queued, self._lookup_queue = self._lookup_queue, []
            for participant in queued:
                self._resolve(participant, name_key(participant.name))

    async def _lookup(self, batch: list[_Participant]) -> None:
        fingerprints: dict[int, str | None] = {}
        try:
            collector = await self._console.query(
                WHO_COMMAND, WhoReplyCollector(), reply_timeout=self._lookup_timeout
            )
            fingerprints = {ent: row.fingerprint for ent, row in collector.rows.items()}
        except (InternalQueryError, NotRunningError, SupervisorError) as exc:
            log.warning("fingerprint lookup failed (%s); identifying by name for this visit", exc)
        for participant in batch:
            if participant.key is not None:
                continue
            fingerprint = fingerprints.get(participant.ent)
            if fingerprint:
                self._resolve(participant, "fp:" + fingerprint)
            else:
                self._resolve(participant, name_key(participant.name))

    def _resolve(self, participant: _Participant, key: str) -> None:
        if participant.key is not None:
            return
        participant.key = key
        self._attach_session(participant)

    # -- sessions (D3) ------------------------------------------------------------------
    def _attach_session(self, participant: _Participant) -> None:
        assert participant.key is not None
        existing = self._sessions.get(participant.ent)
        if (
            existing is not None
            and existing.awaiting_since is not None
            and existing.key == participant.key
            and participant.left_at is None
        ):
            # The same player re-joined the slot after a map change: one visit.
            existing.awaiting_since = None
            existing.participant = participant
            participant.session = existing
            return
        if existing is not None:
            ended = existing.awaiting_since
            self._end_session(existing, int(ended if ended is not None else self._clock()))
        session = _Session(
            ent=participant.ent,
            key=participant.key,
            started_at=participant.joined_at,
            participant=participant,
            last_touch=participant.joined_at,
        )
        participant.session = session
        if participant.left_at is not None:
            session.ended_at = max(participant.left_at, session.started_at)
            self._closed.append(session)
        else:
            self._sessions[participant.ent] = session

    def _end_session(self, session: _Session, at: int) -> None:
        if session.ended_at is not None:
            return
        session.ended_at = max(at, session.started_at)
        session.awaiting_since = None
        if self._sessions.get(session.ent) is session:
            del self._sessions[session.ent]
        self._closed.append(session)

    def _close_all_sessions(self, at: int) -> None:
        for session in list(self._sessions.values()):
            self._end_session(session, at)

    def _expire_awaiting(self, now: float) -> None:
        """Sessions whose slot never re-joined end at the map change that began the wait."""
        for session in list(self._sessions.values()):
            if session.awaiting_since is not None and now - session.awaiting_since >= self._grace:
                self._end_session(session, int(session.awaiting_since))

    def _on_state(self, _frm: RunState, to: RunState) -> None:
        if to not in (RunState.STOPPED, RunState.STARTING) or not self.enabled:
            return
        now = int(self._clock())
        # Anyone still connected stops being so at the moment the server did.
        self._close_all_sessions(now)
        if self._lookup_task is not None and not self._lookup_task.done():
            self._lookup_task.cancel()
        self._lookup_queue = []
        self._retire_current(float(now))
        for match in self._retired:
            for participant in match.participants.values():
                if participant.key is None:
                    # never looked up: it can still be recorded, under its name
                    participant.key = name_key(participant.name)
        self._seen_report = None
        self._reports = ReportParser()
        self.request_flush()

    # -- reports (D6) --------------------------------------------------------------------
    def _apply_report(self, report: Report) -> None:
        match = self._match_for(report)
        rows: list[tuple[_Participant, ReportedPlayer]] = []
        for rp in report.players:
            participant = match.participants.get(rp.id) if rp.id is not None else None
            if participant is None:
                participant = self._unknown_participant(match, rp.fingerprint, rp.name, rp.is_bot)
                if participant is None:
                    log.info("a report line for player %s has no identity; skipped", rp.id)
                    continue
            elif participant.key is None:
                # The lookup is still pending: the report's fingerprint is as good as who's.
                if rp.fingerprint and not participant.bot:
                    self._resolve(participant, "fp:" + rp.fingerprint)
                else:
                    self._resolve(participant, name_key(participant.name))
            rows.append((participant, _reported(rp, participant.name)))
        match.reported = True
        if rows:
            self._pending_reports.append(_PendingReport(match, report, rows))
        self.request_flush()

    def _match_for(self, report: Report) -> _Match:
        for candidate in (self._match, *reversed(self._retired)):
            if candidate is not None and candidate.match_id == report.match_id:
                return candidate
        if self._match is not None and self._match.match_id is None:
            # The panel started mid-match: the report names the match we have been in.
            self._match.match_id = report.match_id
            self._match.map = report.map
            self._match.gametype = report.gametype
            return self._match
        match = _Match(
            match_id=report.match_id,
            map=report.map,
            gametype=report.gametype,
            started_at=int(self._clock()) - int(report.duration),
        )
        self._retired.append(match)
        match.superseded_at = float(self._clock())
        return match

    def _unknown_participant(
        self, match: _Match, fingerprint: str | None, name: str | None, is_bot: bool
    ) -> _Participant | None:
        """A reported player the panel never saw join (they joined before it started)."""
        if is_bot and name:
            key = bot_key(name)
        elif fingerprint:
            key = "fp:" + fingerprint
        elif name:
            key = name_key(name)
        else:
            return None
        return _Participant(
            match=match,
            pid=-1,
            ent=-1,
            name=name or "",
            bot=is_bot,
            joined_at=int(self._clock()),
            key=key,
            names=[name] if name else [],
        )

    # -- flushing (D4) ---------------------------------------------------------------------
    def request_flush(self) -> None:
        """Ask the flush task to write now rather than at its next interval."""
        self._flush_requested.set()

    async def _flush_loop(self) -> None:
        while self._running:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._flush_requested.wait(), self._flush_interval)
            self._flush_requested.clear()
            await self.flush()

    async def flush(self) -> None:
        """Write everything pending in one transaction. Never raises."""
        if not self.enabled:
            return
        async with self._flush_lock:
            try:
                await self._flush_locked()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("player history could not be written; will retry")

    def _tracked_matches(self) -> list[_Match]:
        return [*self._retired, *([self._match] if self._match is not None else [])]

    def _build_plan(self, now: int) -> tuple[_Plan, dict[int, object]]:
        """Snapshot what has to be written. ``refs`` maps the plan's ids back to objects."""
        self._expire_awaiting(float(now))
        refs: dict[int, object] = {}
        plan = _Plan(now=now)
        seen_players: set[int] = set()

        def add_player(p: _Participant) -> None:
            if id(p) in seen_players or p.key is None:
                return
            seen_players.add(id(p))
            if p.db_id is not None and not p.names:
                return
            refs[id(p)] = p
            plan.players.append(
                _PlanPlayer(
                    ref=id(p),
                    key=p.key,
                    is_bot=p.bot,
                    db_id=p.db_id,
                    names=tuple(p.names),
                    fallback_name=p.name or "?",
                )
            )

        match_refs: set[int] = set()

        def add_match(m: _Match) -> None:
            if id(m) in match_refs or m.match_id is None:
                return
            match_refs.add(id(m))
            refs[id(m)] = m
            plan.matches.append(
                _PlanMatch(id(m), m.match_id, m.map, m.gametype, m.started_at, m.pk)
            )

        for match in self._tracked_matches():
            for p in match.participants.values():
                add_player(p)
                if p.key is not None and p.dirty and match.match_id is not None:
                    if p.frags or p.deaths or p.suicides or p.teamkills:
                        add_match(match)
                        refs[id(p)] = p
                        plan.counters.append(
                            _PlanCounter(
                                id(p),
                                p.db_id,
                                id(match),
                                (p.frags, p.deaths, p.suicides, p.teamkills),
                                p.name,
                            )
                        )
        for pending in self._pending_reports:
            if pending.match.match_id is None:
                continue
            add_match(pending.match)
            rows = []
            for p, reported in pending.players:
                add_player(p)
                refs[id(p)] = p
                rows.append((id(p), p.db_id, reported))
            refs[id(pending)] = pending
            plan.reports.append(
                _PlanReport(
                    id(pending),
                    id(pending.match),
                    pending.report.finished,
                    pending.report.duration,
                    tuple(rows),
                    pending.report.teams,
                )
            )
        for session in [*self._sessions.values(), *self._closed]:
            p = session.participant
            if p is None or p.key is None:
                continue
            closing = session.ended_at is not None and not session.end_written
            due = session.pk is None or closing or now - session.last_touch >= _TOUCH_INTERVAL
            if not due:
                continue
            add_player(p)
            refs[id(session)] = session
            refs[id(p)] = p
            plan.sessions.append(
                _PlanSession(
                    ref=id(session),
                    player_ref=id(p),
                    player_db_id=p.db_id,
                    started_at=session.started_at,
                    pk=session.pk,
                    ended_at=session.ended_at,
                    end_written=session.end_written,
                )
            )
        return plan, refs

    @staticmethod
    def _execute(plan: _Plan, ops: Ops) -> _Result:
        """The transaction. Runs on the store's thread and touches only the plan."""
        result = _Result()
        db_ids: dict[int, int] = {}
        for pp in plan.players:
            db_id = pp.db_id
            names = pp.names or (pp.fallback_name,)
            if db_id is None:
                db_id = ops.get_or_create_player(pp.key, names[-1], is_bot=pp.is_bot, now=plan.now)
                result.db_ids[pp.ref] = db_id
            for name in names:
                ops.upsert_alias(db_id, name, plan.now)
            db_ids[pp.ref] = db_id

        pks: dict[int, int] = {}
        for pm in plan.matches:
            pks[pm.ref] = ops.upsert_match(pm.match_id, pm.map, pm.gametype, pm.started_at)
            result.match_pks[pm.ref] = pks[pm.ref]

        for ps in plan.sessions:
            db_id = db_ids.get(ps.player_ref, ps.player_db_id)
            if db_id is None:
                continue
            pk = ps.pk
            if pk is None:
                pk = ops.open_session(db_id, ps.started_at)
                result.session_pks[ps.ref] = pk
            if ps.ended_at is not None:
                if not ps.end_written:
                    ops.close_session(pk, ps.ended_at)
                    ops.touch_player(db_id, ps.ended_at)
                    result.sessions_closed.add(ps.ref)
            else:
                ops.touch_player(db_id, plan.now)

        for index, pc in enumerate(plan.counters):
            db_id = db_ids.get(pc.player_ref, pc.player_db_id)
            pk = pks.get(pc.match_ref)
            if db_id is None or pk is None:
                continue
            frags, deaths, suicides, teamkills = pc.deltas
            ops.add_counters(
                pk,
                db_id,
                frags=frags,
                deaths=deaths,
                suicides=suicides,
                teamkills=teamkills,
                name=pc.name,
            )
            result.counters_written.add(index)

        for pr in plan.reports:
            pk = pks.get(pr.match_ref)
            if pk is None:
                continue
            rows = []
            for player_ref, known, reported in pr.rows:
                db_id = db_ids.get(player_ref, known)
                if db_id is not None:
                    rows.append((db_id, reported))
            ops.apply_report(
                pk, finished=pr.finished, duration=pr.duration, players=rows, teams=pr.teams
            )
            result.reports_written.add(pr.ref)
        return result

    async def _flush_locked(self) -> None:
        plan, refs = self._build_plan(int(self._clock()))
        if plan.empty:
            self._release()
            return
        result = await self._store.transact(lambda ops: self._execute(plan, ops))

        # Committed: reflect it in memory. Events that arrived during the write are kept.
        for pp in plan.players:
            participant = refs[pp.ref]
            assert isinstance(participant, _Participant)
            if pp.ref in result.db_ids:
                participant.db_id = result.db_ids[pp.ref]
            del participant.names[: len(pp.names)]
        for pm in plan.matches:
            match = refs[pm.ref]
            assert isinstance(match, _Match)
            match.pk = result.match_pks.get(pm.ref, match.pk)
        for index in result.counters_written:
            pc = plan.counters[index]
            participant = refs[pc.player_ref]
            assert isinstance(participant, _Participant)
            frags, deaths, suicides, teamkills = pc.deltas
            participant.frags -= frags
            participant.deaths -= deaths
            participant.suicides -= suicides
            participant.teamkills -= teamkills
        for ps in plan.sessions:
            session = refs[ps.ref]
            assert isinstance(session, _Session)
            if ps.ref in result.session_pks:
                session.pk = result.session_pks[ps.ref]
            session.last_touch = plan.now
            if ps.ref in result.sessions_closed or (ps.ended_at is not None and ps.end_written):
                session.end_written = True
        self._closed = [s for s in self._closed if not s.end_written]
        done = [r for r in plan.reports if r.ref in result.reports_written]
        self._pending_reports = [
            pending for pending in self._pending_reports if id(pending) not in {r.ref for r in done}
        ]
        self._release()

    def _release(self) -> None:
        """Drop the participant table of a finished match once nothing refers to it."""
        keep: list[_Match] = []
        now = self._clock()
        waiting = {id(p.match) for p in self._pending_reports}
        for match in self._retired:
            idle = not any(p.dirty for p in match.participants.values())
            lapsed = match.superseded_at is not None and now - match.superseded_at >= self._grace
            if idle and (match.reported or lapsed) and id(match) not in waiting:
                continue
            keep.append(match)
        self._retired = keep


# Scoreboard labels the game keeps hidden, so the history does not keep them either.
_HIDDEN_LABELS = frozenset({"elo", "rounds_pl"})


def _reported(rp: ReportPlayer, fallback_name: str | None = None) -> ReportedPlayer:
    """What a report says about one player. The name is the report's, else ``fallback_name``
    (the name the recorder saw them use), else none."""
    events = rp.events
    board = scoreboard(events)
    rank = events.get("rank")
    pos = events.get("scoreboardpos")
    return ReportedPlayer(
        score=float(board.get("score", 0.0)),
        kills=float(board.get("kills", 0.0)),
        alivetime=float(events.get("alivetime", 0.0)),
        dmg=float(board.get("dmg", 0.0)),
        dmgtaken=float(board.get("dmgtaken", 0.0)),
        wins=int(events.get("wins", 0)),
        rank=int(rank) if rank is not None else None,
        avglatency=float(events.get("avglatency", 0.0)),
        scoreboard_valid=bool(events.get("scoreboardvalid", 0)),
        joined=int(events.get("joins", 0)),
        weapons=weapon_stats(events) or None,
        achievements=achievements(events) or None,
        extra=extra_labels(board) or None,
        team=rp.team,
        board_pos=int(pos) if pos else None,
        name=rp.name or fallback_name or None,
        scores={k: float(v) for k, v in board.items() if k not in _HIDDEN_LABELS} or None,
    )
