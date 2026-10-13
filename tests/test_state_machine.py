"""Legal and illegal lifecycle transitions."""

from __future__ import annotations

import itertools

import pytest

from xonotic_webui.supervisor.state import RunState, StateMachine, TransitionError

LEGAL = {
    (RunState.STOPPED, RunState.STARTING),
    (RunState.STARTING, RunState.RUNNING),
    (RunState.STARTING, RunState.STOPPED),
    (RunState.STARTING, RunState.STOPPING),
    (RunState.RUNNING, RunState.STOPPING),
    (RunState.RUNNING, RunState.STOPPED),
    (RunState.STOPPING, RunState.STOPPED),
}


def machine_in(state: RunState) -> StateMachine:
    sm = StateMachine()
    path = {
        RunState.STOPPED: [],
        RunState.STARTING: [RunState.STARTING],
        RunState.RUNNING: [RunState.STARTING, RunState.RUNNING],
        RunState.STOPPING: [RunState.STARTING, RunState.RUNNING, RunState.STOPPING],
    }[state]
    for step in path:
        sm.transition(step)
    assert sm.state is state
    return sm


def test_initial_state_is_stopped() -> None:
    assert StateMachine().state is RunState.STOPPED


@pytest.mark.parametrize(("frm", "to"), sorted(LEGAL))
def test_legal_transition(frm: RunState, to: RunState) -> None:
    sm = machine_in(frm)
    assert sm.can(to)
    assert sm.transition(to) == (frm, to)
    assert sm.state is to


@pytest.mark.parametrize(
    ("frm", "to"),
    [(f, t) for f, t in itertools.product(RunState, RunState) if f != t and (f, t) not in LEGAL],
)
def test_illegal_transition_raises_and_leaves_state(frm: RunState, to: RunState) -> None:
    sm = machine_in(frm)
    assert not sm.can(to)
    with pytest.raises(TransitionError):
        sm.transition(to)
    assert sm.state is frm


def test_same_state_transition_is_a_noop_and_silent() -> None:
    sm = machine_in(RunState.RUNNING)
    seen: list[tuple[RunState, RunState]] = []
    sm.subscribe(lambda f, t: seen.append((f, t)))
    assert sm.transition(RunState.RUNNING) == (RunState.RUNNING, RunState.RUNNING)
    assert seen == []


def test_compare_and_transition() -> None:
    sm = StateMachine()
    assert sm.compare_and_transition(RunState.RUNNING, RunState.STOPPING) is None  # wrong state
    assert sm.state is RunState.STOPPED
    assert sm.compare_and_transition(RunState.STOPPED, RunState.STARTING) == (
        RunState.STOPPED,
        RunState.STARTING,
    )
    assert sm.state is RunState.STARTING


def test_compare_and_transition_still_rejects_an_illegal_target() -> None:
    sm = machine_in(RunState.RUNNING)
    with pytest.raises(TransitionError):
        sm.compare_and_transition(RunState.RUNNING, RunState.STARTING)
    assert sm.state is RunState.RUNNING


def test_listeners_are_notified_in_order() -> None:
    sm = StateMachine()
    seen: list[tuple[RunState, RunState]] = []
    sm.subscribe(lambda f, t: seen.append((f, t)))
    sm.transition(RunState.STARTING)
    sm.transition(RunState.RUNNING)
    assert seen == [
        (RunState.STOPPED, RunState.STARTING),
        (RunState.STARTING, RunState.RUNNING),
    ]
