"""Supervisor behaviour against the fake dedicated server (server-lifecycle spec)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

from tests.helpers import make_settings, process_alive
from xonotic_webui.settings import Settings
from xonotic_webui.supervisor import (
    AlreadyRunningError,
    NoInstallationError,
    NotRunningError,
    ReadinessTimeoutError,
    RunState,
    StartFailedError,
    Supervisor,
    TransitionInProgressError,
)
from xonotic_webui.supervisor import supervisor as supervisor_module


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Select fake-server behaviour for the next spawn(s)."""

    def apply(spec: str) -> None:
        monkeypatch.setenv("FAKE_XONOTIC", spec)

    monkeypatch.delenv("FAKE_XONOTIC", raising=False)
    return apply


@pytest.fixture(autouse=True)
def _fast_escalation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(supervisor_module, "_TERM_GRACE", 0.5)
    monkeypatch.setattr(supervisor_module, "_KILL_WAIT", 3.0)


@pytest.fixture
async def make_sup() -> AsyncIterator[Callable[..., Supervisor]]:
    created: list[Supervisor] = []

    def factory(settings: Settings, **kwargs: object) -> Supervisor:
        sup = Supervisor(settings, **kwargs)  # type: ignore[arg-type]
        created.append(sup)
        return sup

    yield factory
    for sup in created:
        await sup.aclose()


@pytest.fixture
def sup(settings: Settings, make_sup: Callable[..., Supervisor]) -> Supervisor:
    return make_sup(settings, probe_after=0.3, probe_interval=0.2)


async def wait_for(predicate: Callable[[], bool], timeout: float = 8.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


def launch_record(settings: Settings) -> dict:
    return json.loads((settings.userdir / "fake-launch.json").read_text())


# --- initial state and start ---------------------------------------------------


async def test_initial_state_is_stopped(sup: Supervisor) -> None:
    assert sup.state is RunState.STOPPED
    assert sup.pid is None
    assert sup.last_crash is None
    assert not sup.restart_abandoned


async def test_start_reaches_running_and_launches_as_designed(
    sup: Supervisor, settings: Settings, fake: Callable[[str], None]
) -> None:
    states: list[RunState] = []
    sup.subscribe_state(lambda _f, t: states.append(t))
    await sup.start()

    assert sup.state is RunState.RUNNING
    assert states == [RunState.STARTING, RunState.RUNNING]
    assert process_alive(sup.pid or -1)

    rec = launch_record(settings)
    assert rec["userdir"] == str(settings.userdir)
    assert rec["port"] == str(settings.game_port)
    assert rec["serverconfig"] == "xonotic-webui.cfg"
    assert rec["cwd"] == str(settings.game_root)
    assert ["+sys_colortranslation", "2"] == rec["argv"][4:6]
    # the wrapper runs the operator's config then forces what the panel depends on
    wrapper = rec["wrapper_cfg"]
    assert wrapper.index("exec server.cfg") < wrapper.index("sv_eventlog 1")
    # the panel's generated settings run between the operator's config and the forced cvars
    assert wrapper.index("exec server.cfg") < wrapper.index("exec xonotic-webui-settings.cfg")
    assert wrapper.index("exec xonotic-webui-settings.cfg") < wrapper.index("sv_eventlog 1")
    assert "sv_eventlog_console 1" in wrapper
    assert "sv_eventlog_ipv6_delimiter 1" in wrapper
    assert "sys_colortranslation 2" in wrapper
    assert "g_playerstats_gamereport_uri -" in wrapper


async def test_wrapper_line_order_is_server_cfg_then_settings_then_forced_cvars(
    sup: Supervisor, settings: Settings
) -> None:
    await sup.start()
    lines = [
        ln for ln in launch_record(settings)["wrapper_cfg"].splitlines() if not ln.startswith("//")
    ]
    assert lines == [
        "exec server.cfg",
        "exec xonotic-webui-settings.cfg",
        "sv_eventlog 1",
        "sv_eventlog_console 1",
        "sv_eventlog_ipv6_delimiter 1",
        "sys_colortranslation 2",
        "g_playerstats_gamereport_uri -",
    ]


async def test_a_raising_line_sink_does_not_stop_the_next(
    settings: Settings, make_sup: Callable[..., Supervisor], caplog: pytest.LogCaptureFixture
) -> None:
    seen: list[str] = []

    def bad(_line: str) -> None:
        raise RuntimeError("boom")

    sup = make_sup(settings, probe_after=0.3, probe_interval=0.2)
    sup.add_line_sink(bad)
    sup.add_line_sink(seen.append)
    await sup.start()

    assert any(":gamestart:" in line for line in seen)
    assert "line sink raised" in caplog.text


async def test_an_empty_store_produces_a_header_only_settings_config(
    sup: Supervisor, settings: Settings
) -> None:
    await sup.start()
    cfg = launch_record(settings)["configs"]["xonotic-webui-settings.cfg"]
    assert cfg.startswith("// Managed by xonotic-webui")
    assert [ln for ln in cfg.splitlines() if not ln.startswith("//")] == []


async def test_the_settings_config_is_rendered_again_on_every_start(
    settings: Settings, make_sup: Callable[..., Supervisor]
) -> None:
    texts = iter(['hostname "first"\n', 'hostname "second"\n'])
    sup = make_sup(settings, settings_cfg=lambda: next(texts))
    await sup.start()
    assert launch_record(settings)["configs"]["xonotic-webui-settings.cfg"] == 'hostname "first"\n'
    await sup.restart()
    assert launch_record(settings)["configs"]["xonotic-webui-settings.cfg"] == 'hostname "second"\n'


async def test_a_failing_renderer_does_not_stop_the_server_starting(
    settings: Settings, make_sup: Callable[..., Supervisor]
) -> None:
    def boom() -> str:
        raise RuntimeError("settings.json is broken")

    sup = make_sup(settings, settings_cfg=boom)
    await sup.start()
    assert sup.state is RunState.RUNNING
    cfg = launch_record(settings)["configs"]["xonotic-webui-settings.cfg"]
    assert [ln for ln in cfg.splitlines() if not ln.startswith("//")] == []
    assert any("panel settings not applied" in ln.text for ln in sup.console.snapshot())


async def test_start_requires_an_installation(
    tmp_path: Path, make_sup: Callable[..., Supervisor]
) -> None:
    s = make_settings(tmp_path, game_root=tmp_path / "missing")
    sup = make_sup(s)
    with pytest.raises(NoInstallationError, match="not installed"):
        await sup.start()
    assert sup.state is RunState.STOPPED
    assert sup.pid is None


async def test_never_ready_is_a_failed_start(
    tmp_path: Path, make_sup: Callable[..., Supervisor], fake: Callable[[str], None]
) -> None:
    fake("noready")
    s = make_settings(tmp_path, readiness_timeout=1.0)
    sup = make_sup(s, probe_after=60)
    with pytest.raises(ReadinessTimeoutError, match="did not become ready"):
        await sup.start()
    assert sup.state is RunState.STOPPED
    assert sup.pid is None
    assert sup.last_start_failure is not None
    assert "did not become ready" in sup.last_start_failure.reason
    # the process was stopped, not left behind
    pid = json.loads((s.userdir / "fake-launch.json").read_text())["pid"]
    await wait_for(lambda: not process_alive(pid))


async def test_exit_during_startup_is_a_failed_start(
    sup: Supervisor, fake: Callable[[str], None]
) -> None:
    fake("exit_early=3")
    with pytest.raises(StartFailedError, match="status 3"):
        await sup.start()
    assert sup.state is RunState.STOPPED
    assert sup.last_start_failure is not None
    assert sup.last_start_failure.exit_code == 3
    assert sup.last_crash is None  # a failed start is not a crash


async def test_readiness_falls_back_to_a_status_reply(
    sup: Supervisor, fake: Callable[[str], None]
) -> None:
    # No event log at all, so no :gamestart:; readiness must come from `status`.
    fake("eventlog_off,map_delay=0.1")
    await sup.start()
    assert sup.state is RunState.RUNNING


# --- stop and restart -----------------------------------------------------------


async def test_stop_is_graceful_and_not_a_crash(sup: Supervisor) -> None:
    await sup.start()
    pid = sup.pid or -1
    states: list[RunState] = []
    sup.subscribe_state(lambda _f, t: states.append(t))

    await sup.stop()

    assert states == [RunState.STOPPING, RunState.STOPPED]
    assert sup.state is RunState.STOPPED
    assert sup.last_crash is None
    assert not process_alive(pid)


async def test_stop_escalates_when_quit_is_ignored(
    tmp_path: Path, make_sup: Callable[..., Supervisor], fake: Callable[[str], None]
) -> None:
    fake("ignore_quit")
    s = make_settings(tmp_path, shutdown_timeout=1.0)
    sup = make_sup(s)
    await sup.start()
    pid = sup.pid or -1
    await sup.stop()  # quit ignored -> SIGTERM
    assert sup.state is RunState.STOPPED
    assert not process_alive(pid)
    assert sup.last_crash is None


async def test_stop_kills_a_server_that_ignores_everything(
    tmp_path: Path, make_sup: Callable[..., Supervisor], fake: Callable[[str], None]
) -> None:
    fake("ignore_quit,ignore_term")
    s = make_settings(tmp_path, shutdown_timeout=1.0)
    sup = make_sup(s)
    await sup.start()
    pid = sup.pid or -1
    await sup.stop()  # quit ignored, SIGTERM ignored -> SIGKILL
    assert sup.state is RunState.STOPPED
    assert not process_alive(pid)


async def test_restart_running_server_is_one_operation(sup: Supervisor) -> None:
    await sup.start()
    first_pid = sup.pid
    states: list[RunState] = []
    sup.subscribe_state(lambda _f, t: states.append(t))

    await sup.restart()

    assert states == [RunState.STOPPING, RunState.STOPPED, RunState.STARTING, RunState.RUNNING]
    assert sup.state is RunState.RUNNING
    assert sup.pid != first_pid
    assert not process_alive(first_pid or -1)


async def test_restart_stopped_server_starts_it(sup: Supervisor) -> None:
    assert sup.state is RunState.STOPPED
    await sup.restart()
    assert sup.state is RunState.RUNNING


# --- conflicting operations ------------------------------------------------------


async def test_start_while_running_is_rejected_and_undisturbed(sup: Supervisor) -> None:
    await sup.start()
    pid = sup.pid
    with pytest.raises(AlreadyRunningError):
        await sup.start()
    assert sup.state is RunState.RUNNING
    assert sup.pid == pid


async def test_stop_while_stopped_is_rejected(sup: Supervisor) -> None:
    with pytest.raises(NotRunningError):
        await sup.stop()


async def test_requests_during_a_start_are_rejected(
    sup: Supervisor, fake: Callable[[str], None]
) -> None:
    fake("startup_delay=1.0")
    starting = asyncio.create_task(sup.start())
    await wait_for(lambda: sup.state is RunState.STARTING)

    with pytest.raises(AlreadyRunningError):
        await sup.start()
    with pytest.raises(TransitionInProgressError):
        await sup.stop()
    with pytest.raises(TransitionInProgressError):
        await sup.restart()

    await starting
    assert sup.state is RunState.RUNNING


async def test_transition_in_progress_reflects_each_state(
    sup: Supervisor, fake: Callable[[str], None]
) -> None:
    assert sup.transition_in_progress() is False  # stopped

    fake("startup_delay=1.0,quit_delay=1.0")
    starting = asyncio.create_task(sup.start())
    await wait_for(lambda: sup.state is RunState.STARTING)
    assert sup.transition_in_progress() is True  # starting
    await starting
    assert sup.state is RunState.RUNNING
    assert sup.transition_in_progress() is False  # running

    stopping = asyncio.create_task(sup.stop())
    await wait_for(lambda: sup.state is RunState.STOPPING)
    assert sup.transition_in_progress() is True  # stopping
    await stopping
    assert sup.transition_in_progress() is False  # stopped again


async def test_transition_in_progress_while_the_operation_lock_is_held(sup: Supervisor) -> None:
    async with sup._op_lock:
        assert sup.state is RunState.STOPPED
        assert sup.transition_in_progress() is True
    assert sup.transition_in_progress() is False


async def test_requests_during_a_stop_are_rejected(
    sup: Supervisor, fake: Callable[[str], None]
) -> None:
    fake("quit_delay=1.0")
    await sup.start()
    stopping = asyncio.create_task(sup.stop())
    await wait_for(lambda: sup.state is RunState.STOPPING)

    with pytest.raises(TransitionInProgressError):
        await sup.start()
    with pytest.raises(TransitionInProgressError):
        await sup.stop()
    with pytest.raises(TransitionInProgressError):
        await sup.restart()

    await stopping
    assert sup.state is RunState.STOPPED


# --- crashes ------------------------------------------------------------------------


async def test_single_crash_restarts_and_is_recorded(sup: Supervisor) -> None:
    await sup.start()
    first_pid = sup.pid
    states: list[RunState] = []
    sup.subscribe_state(lambda _f, t: states.append(t))

    await sup.send_command("fake_crash")
    await wait_for(lambda: sup.state is RunState.RUNNING and sup.pid != first_pid)

    assert states[:3] == [RunState.STOPPED, RunState.STARTING, RunState.RUNNING]
    assert sup.last_crash is not None
    assert sup.last_crash.exit_code == 139
    assert sup.last_crash.at
    assert not sup.restart_abandoned


async def test_crash_loop_is_abandoned(
    tmp_path: Path, make_sup: Callable[..., Supervisor], fake: Callable[[str], None]
) -> None:
    fake("crash_after=0.05")
    s = make_settings(tmp_path, crash_restart_threshold=2, crash_restart_window=60.0)
    sup = make_sup(s)
    await sup.start()  # runs, then crashes on its own, repeatedly

    await wait_for(lambda: sup.restart_abandoned, timeout=15)
    assert sup.state is RunState.STOPPED
    assert sup.pid is None
    assert sup.last_crash is not None
    # exactly threshold restarts were attempted, then it gave up
    assert sup.last_crash.exit_code == 139

    # and it stays down
    await asyncio.sleep(0.5)
    assert sup.state is RunState.STOPPED


async def test_restart_limiting_disabled_does_not_restart(
    tmp_path: Path, make_sup: Callable[..., Supervisor]
) -> None:
    s = make_settings(tmp_path, crash_restart_threshold=0)
    sup = make_sup(s)
    await sup.start()
    await sup.send_command("fake_crash")
    await wait_for(lambda: sup.state is RunState.STOPPED and sup.last_crash is not None)
    await asyncio.sleep(0.5)
    assert sup.state is RunState.STOPPED
    assert sup.pid is None
    assert not sup.restart_abandoned


async def test_operator_start_after_abandonment_resets_it(
    tmp_path: Path, make_sup: Callable[..., Supervisor], fake: Callable[[str], None]
) -> None:
    fake("crash_after=0.05")
    s = make_settings(tmp_path, crash_restart_threshold=1, crash_restart_window=60.0)
    sup = make_sup(s)
    await sup.start()
    await wait_for(lambda: sup.restart_abandoned, timeout=15)

    fake("")  # healthy again
    await sup.start()
    assert sup.state is RunState.RUNNING
    assert not sup.restart_abandoned


# --- intended run state ---------------------------------------------------------------


def desired(settings: Settings) -> bool | None:
    try:
        return json.loads(settings.state_file.read_text())["desired_running"]
    except FileNotFoundError:
        return None


async def test_operator_actions_persist_intent(sup: Supervisor, settings: Settings) -> None:
    assert desired(settings) is None
    await sup.start()
    assert desired(settings) is True
    await sup.stop()
    assert desired(settings) is False


async def test_restart_while_running_keeps_intent_running(
    sup: Supervisor, settings: Settings
) -> None:
    await sup.start()
    await sup.restart()
    assert desired(settings) is True


async def test_crash_does_not_alter_intent(
    tmp_path: Path, make_sup: Callable[..., Supervisor]
) -> None:
    s = make_settings(tmp_path, crash_restart_threshold=0)
    sup = make_sup(s)
    await sup.start()
    await sup.send_command("fake_crash")
    await wait_for(lambda: sup.state is RunState.STOPPED and sup.last_crash is not None)
    assert desired(s) is True


async def test_restore_starts_a_server_that_was_running(
    settings: Settings, make_sup: Callable[..., Supervisor]
) -> None:
    first = make_sup(settings)
    await first.start()
    await first.aclose()  # the panel stops; the server was meant to be running
    assert desired(settings) is True

    second = make_sup(settings)
    await second.restore()
    assert second.state is RunState.RUNNING


async def test_restore_leaves_a_deliberately_stopped_server_stopped(
    settings: Settings, make_sup: Callable[..., Supervisor]
) -> None:
    first = make_sup(settings)
    await first.start()
    await first.stop()

    second = make_sup(settings)
    await second.restore()
    assert second.state is RunState.STOPPED


async def test_restore_with_no_state_file_does_nothing(sup: Supervisor) -> None:
    await sup.restore()
    assert sup.state is RunState.STOPPED


# --- panel shutdown -----------------------------------------------------------------------


async def test_panel_shutdown_leaves_no_orphan(sup: Supervisor) -> None:
    await sup.start()
    pid = sup.pid or -1
    assert process_alive(pid)

    await sup.aclose()

    assert not process_alive(pid)
    assert sup.state is RunState.STOPPED


async def test_panel_shutdown_during_startup_aborts_it(
    sup: Supervisor, settings: Settings, fake: Callable[[str], None]
) -> None:
    fake("noready")
    starting = asyncio.create_task(sup.start())
    await wait_for(lambda: sup.state is RunState.STARTING)
    pid = sup.pid or -1

    await sup.aclose()
    with pytest.raises(TransitionInProgressError):
        await starting

    assert not process_alive(pid)
    assert sup.state is RunState.STOPPED


async def test_run_boundary_marker_and_history_survive_restart(sup: Supervisor) -> None:
    await sup.start()
    first_lines = len(sup.console)
    assert first_lines > 0
    await sup.restart()
    texts = [line.text for line in sup.console.snapshot()]
    assert any("restarting" in t for t in texts)
    assert any("server starting" in t for t in texts)
    assert len(texts) > first_lines  # earlier output retained
