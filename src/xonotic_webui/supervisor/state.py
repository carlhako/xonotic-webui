"""The four-state lifecycle model (server-lifecycle spec).

``stopped`` -> ``starting`` -> ``running`` -> ``stopping`` -> ``stopped``. A crash is not
a state: the process is gone, so the state is ``stopped`` and the crash is recorded
separately. Transitions are guarded so an illegal one raises instead of corrupting state.
"""

from __future__ import annotations

import enum
from collections.abc import Callable


class RunState(enum.StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"


_ALLOWED: dict[RunState, frozenset[RunState]] = {
    RunState.STOPPED: frozenset({RunState.STARTING}),
    RunState.STARTING: frozenset({RunState.RUNNING, RunState.STOPPED, RunState.STOPPING}),
    RunState.RUNNING: frozenset({RunState.STOPPING, RunState.STOPPED}),
    RunState.STOPPING: frozenset({RunState.STOPPED}),
}

StateListener = Callable[[RunState, RunState], None]


class TransitionError(RuntimeError):
    """An illegal lifecycle transition was attempted."""

    def __init__(self, frm: RunState, to: RunState) -> None:
        super().__init__(f"illegal lifecycle transition {frm.value} -> {to.value}")
        self.frm = frm
        self.to = to


class StateMachine:
    """Holder of the current state with guarded transitions.

    Everything runs on the event loop, so no lock is needed: a method that does not
    await is atomic with respect to other tasks.
    """

    def __init__(self, initial: RunState = RunState.STOPPED) -> None:
        self._state = initial
        self._listeners: list[StateListener] = []

    @property
    def state(self) -> RunState:
        return self._state

    def subscribe(self, listener: StateListener) -> None:
        self._listeners.append(listener)

    def can(self, to: RunState) -> bool:
        return to in _ALLOWED[self._state]

    def transition(self, to: RunState) -> tuple[RunState, RunState]:
        frm = self._state
        if to == frm:
            return frm, to
        if to not in _ALLOWED[frm]:
            raise TransitionError(frm, to)
        self._state = to
        self._notify(frm, to)
        return frm, to

    def compare_and_transition(
        self, expected: RunState, to: RunState
    ) -> tuple[RunState, RunState] | None:
        """Transition only if the current state is ``expected``.

        Returns ``(from, to)`` on success, or ``None`` if the state was something else
        (the caller then reports the conflict). An illegal target still raises.
        """
        if self._state != expected:
            return None
        return self.transition(to)

    def _notify(self, frm: RunState, to: RunState) -> None:
        for listener in list(self._listeners):
            listener(frm, to)
