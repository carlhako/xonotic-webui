"""panel-self-update: requesting, following and reporting an upgrade."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from tests.helpers import make_settings
from xonotic_webui.selfupdate import upgrade as upgrade_mod
from xonotic_webui.selfupdate.release_check import ReleaseChecker
from xonotic_webui.selfupdate.upgrade import UpgradeError, UpgradeService, manual_command
from xonotic_webui.settings import Settings
from xonotic_webui.supervisor import RunState, Supervisor
from xonotic_webui.supervisor import supervisor as supervisor_module


@pytest.fixture(autouse=True)
def _fast_escalation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(supervisor_module, "_TERM_GRACE", 0.5)
    monkeypatch.setattr(supervisor_module, "_KILL_WAIT", 3.0)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path, release_api_url="https://api.test", upgrade_timeout_seconds=30.0)


@pytest.fixture
async def sup(settings: Settings) -> AsyncIterator[Supervisor]:
    supervisor = Supervisor(settings, probe_after=0.3, probe_interval=0.2)
    yield supervisor
    await supervisor.aclose()


def _checker(settings: Settings, tag: str | None = "v0.5.0") -> ReleaseChecker:
    def handle(_req: httpx.Request) -> httpx.Response:
        if tag is None:
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "tag_name": tag,
                "html_url": f"https://github.com/carlhako/xonotic-webui/releases/tag/{tag}",
            },
        )

    c = ReleaseChecker(settings, current="0.4.0", transport=httpx.MockTransport(handle))
    c.check_now()
    return c


def _install_helper(settings: Settings) -> None:
    settings.upgrade_helper_path.parent.mkdir(parents=True, exist_ok=True)
    settings.upgrade_helper_path.write_text("#!/usr/bin/python3\n")
    settings.upgrade_status_dir.mkdir(parents=True, exist_ok=True)


def _write_status(settings: Settings, **fields: object) -> None:
    """Write the helper's status. Like the real helper, it echoes the outstanding request's
    id unless the test says otherwise."""
    if "request_id" not in fields:
        pending_file = settings.state_dir / "upgrade_pending.json"
        pending = json.loads(pending_file.read_text()) if pending_file.exists() else {}
        fields["request_id"] = pending.get("request_id")
    settings.upgrade_status_dir.mkdir(parents=True, exist_ok=True)
    (settings.upgrade_status_dir / "status.json").write_text(json.dumps(fields))


def _service(
    sup: Supervisor,
    settings: Settings,
    *,
    tag: str | None = "v0.5.0",
    helper: bool = True,
    current: str = "0.4.0",
) -> UpgradeService:
    if helper:
        _install_helper(settings)
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    return UpgradeService(
        settings, sup, _checker(settings, tag), current=current, poll_seconds=0.01
    )


async def _wait_for(pred, limit: float = 10.0) -> None:
    # Polls files that have no event to await.
    async with asyncio.timeout(limit):
        while not pred():  # noqa: ASYNC110
            await asyncio.sleep(0.01)


async def _concluded(svc: UpgradeService) -> None:
    await _wait_for(lambda: not svc.pending_file.exists())


# -- helper detection -----------------------------------------------------------
async def test_helper_detection(sup: Supervisor, settings: Settings) -> None:
    svc = _service(sup, settings, helper=False)
    assert svc.helper_installed() is False
    assert svc.manual_command() == manual_command(settings)
    _install_helper(settings)
    assert svc.helper_installed() is True
    assert svc.manual_command() is None
    # Both halves are needed: the script and the root-owned status directory.
    settings.upgrade_status_dir.rmdir()
    assert svc.helper_installed() is False


async def test_manual_command_names_the_configured_repo(settings: Settings) -> None:
    assert manual_command(settings) == (
        "curl -fsSL https://github.com/carlhako/xonotic-webui/releases/latest/download/install.sh"
        " | bash"
    )


def test_paths_are_where_the_helper_expects(settings: Settings) -> None:
    svc = UpgradeService(settings, None, None)  # type: ignore[arg-type]
    assert svc.request_file == settings.state_dir / "upgrade" / "request.json"
    assert svc.processing_file == settings.state_dir / "upgrade" / "request.processing"
    assert svc.status_file == settings.upgrade_status_dir / "status.json"


# -- requesting -----------------------------------------------------------------
async def test_request_writes_the_two_files_and_reports_pending(
    sup: Supervisor, settings: Settings
) -> None:
    svc = _service(sup, settings)
    view = await svc.request("0.5.0")

    req = json.loads(svc.request_file.read_text())
    pending = json.loads(svc.pending_file.read_text())
    assert req["tag"] == "v0.5.0"
    assert len(req["request_id"]) == 32
    assert int(req["request_id"], 16) >= 0
    assert req["request_id"] == pending["request_id"]
    assert set(req) == {"tag", "request_id"}
    assert pending["from"] == "0.4.0" and pending["to"] == "0.5.0" and pending["tag"] == "v0.5.0"
    assert pending["requested_at"]
    assert view["state"] == "pending" and view["to"] == "0.5.0"
    assert svc.in_progress()
    await svc.stop()


async def test_a_leading_v_is_accepted_in_the_requested_version(
    sup: Supervisor, settings: Settings
) -> None:
    svc = _service(sup, settings)
    await svc.request("v0.5.0")
    assert json.loads(svc.request_file.read_text())["tag"] == "v0.5.0"
    await svc.stop()


async def test_request_does_not_stop_the_running_game_server(
    sup: Supervisor, settings: Settings
) -> None:
    await sup.start()
    pid = sup.pid
    svc = _service(sup, settings)
    await svc.request("0.5.0")
    await asyncio.sleep(0.1)
    assert sup.state is RunState.RUNNING
    assert sup.pid == pid
    assert sup.desired_running() is True
    await svc.stop()


async def test_request_leaves_a_stopped_server_stopped(sup: Supervisor, settings: Settings) -> None:
    await sup.start()
    await sup.stop()
    svc = _service(sup, settings)
    await svc.request("0.5.0")
    assert sup.state is RunState.STOPPED
    assert sup.desired_running() is False
    await svc.stop()


# -- refusals -------------------------------------------------------------------
def _nothing_written(svc: UpgradeService) -> None:
    assert not svc.request_file.exists()
    assert not svc.pending_file.exists()
    assert not svc.in_progress()


async def test_refused_when_no_update_available(sup: Supervisor, settings: Settings) -> None:
    svc = _service(sup, settings, tag="v0.4.0")
    with pytest.raises(UpgradeError) as exc:
        await svc.request("0.4.0")
    assert exc.value.code == "no_update_available"
    _nothing_written(svc)


async def test_refused_when_availability_unknown(sup: Supervisor, settings: Settings) -> None:
    svc = _service(sup, settings, tag=None)
    with pytest.raises(UpgradeError) as exc:
        await svc.request("0.5.0")
    assert exc.value.code == "no_update_available"
    _nothing_written(svc)


async def test_refused_on_version_mismatch(sup: Supervisor, settings: Settings) -> None:
    svc = _service(sup, settings)
    with pytest.raises(UpgradeError) as exc:
        await svc.request("0.6.0")
    assert exc.value.code == "version_mismatch"
    _nothing_written(svc)


async def test_refused_when_helper_not_installed(sup: Supervisor, settings: Settings) -> None:
    svc = _service(sup, settings, helper=False)
    with pytest.raises(UpgradeError) as exc:
        await svc.request("0.5.0")
    assert exc.value.code == "helper_not_installed"
    _nothing_written(svc)


async def test_refused_when_already_pending(sup: Supervisor, settings: Settings) -> None:
    svc = _service(sup, settings)
    svc.pending_file.write_text(json.dumps({"tag": "v0.5.0", "to": "0.5.0"}))
    with pytest.raises(UpgradeError) as exc:
        await svc.request("0.5.0")
    assert exc.value.code == "upgrade_in_progress"
    assert not svc.request_file.exists()


async def test_second_request_is_refused_while_the_first_is_followed(
    sup: Supervisor, settings: Settings
) -> None:
    svc = _service(sup, settings)
    await svc.request("0.5.0")
    first = svc.request_file.read_text()
    with pytest.raises(UpgradeError) as exc:
        await svc.request("0.5.0")
    assert exc.value.code == "upgrade_in_progress"
    assert svc.request_file.read_text() == first
    await svc.stop()


async def test_refused_during_a_lifecycle_transition(sup: Supervisor, settings: Settings) -> None:
    svc = _service(sup, settings)
    async with sup._op_lock:
        with pytest.raises(UpgradeError) as exc:
            await svc.request("0.5.0")
    assert exc.value.code == "transition_in_progress"
    _nothing_written(svc)


async def test_refusals_are_checked_in_the_documented_order(
    sup: Supervisor, settings: Settings
) -> None:
    # Helper missing AND nothing to upgrade to AND a transition: the earliest wins.
    svc = _service(sup, settings, tag="v0.4.0", helper=False)
    async with sup._op_lock:
        with pytest.raises(UpgradeError) as exc:
            await svc.request("0.9.9")
    assert exc.value.code == "helper_not_installed"

    _install_helper(settings)
    async with sup._op_lock:
        with pytest.raises(UpgradeError) as exc:
            await svc.request("0.9.9")
    assert exc.value.code == "no_update_available"

    svc2 = _service(sup, settings)
    async with sup._op_lock:
        with pytest.raises(UpgradeError) as exc:
            await svc2.request("0.9.9")
    assert exc.value.code == "version_mismatch"


# -- following the helper while this panel is still running -----------------------
@pytest.mark.parametrize("terminal", ["failed", "rejected"])
async def test_helper_failure_is_recorded_and_clears_the_request(
    sup: Supervisor, settings: Settings, terminal: str
) -> None:
    await sup.start()
    svc = _service(sup, settings)
    await svc.request("0.5.0")
    _write_status(settings, tag="v0.5.0", state="running")
    await _wait_for(lambda: svc.view()["state"] == "running")
    _write_status(settings, tag="v0.5.0", state=terminal, error="bad digest", log_tail="tail...")
    await _concluded(svc)

    last = svc.view()
    assert last["state"] == terminal
    assert last["error"] == "bad digest" and last["log_tail"] == "tail..."
    assert last["from"] == "0.4.0" and last["to"] == "0.5.0"
    assert last["finished_at"]
    assert not svc.pending_file.exists() and not svc.request_file.exists()
    assert not svc.in_progress()
    # The game server was never touched.
    assert sup.state is RunState.RUNNING


async def test_installer_rollback_is_a_failure(sup: Supervisor, settings: Settings) -> None:
    # The old panel is back (rolled back) and the helper says the install failed.
    svc = _service(sup, settings, current="0.4.0")
    (settings.state_dir / "upgrade_pending.json").write_text(
        json.dumps(
            {
                "from": "0.4.0",
                "to": "0.5.0",
                "tag": "v0.5.0",
                "request_id": "a" * 32,
                "requested_at": "2999-01-01T00:00:00+00:00",
            }
        )
    )
    _write_status(
        settings,
        tag="v0.5.0",
        state="failed",
        request_id="a" * 32,
        error="installer exited 1",
        log_tail="health check failed; restored previous version",
    )
    svc.start()
    await _concluded(svc)
    last = svc.view()
    assert last["state"] == "failed"
    assert last["error"] == "installer exited 1"
    assert "restored previous version" in last["log_tail"]


async def test_success_reported_while_the_old_panel_is_running_is_a_failure(
    sup: Supervisor, settings: Settings
) -> None:
    svc = _service(sup, settings)
    await svc.request("0.5.0")
    _write_status(settings, tag="v0.5.0", state="succeeded")
    await _concluded(svc)
    last = svc.view()
    assert last["state"] == "failed"
    assert "0.4.0" in last["error"]


async def test_status_for_another_request_is_ignored(sup: Supervisor, settings: Settings) -> None:
    svc = _service(sup, settings)
    await svc.request("0.5.0")
    _write_status(settings, tag="v0.3.0", state="failed", request_id="0" * 32)
    await asyncio.sleep(0.1)
    assert svc.in_progress()
    assert svc.view()["state"] == "pending"
    _write_status(settings, tag="v0.5.0", state="failed")
    await _concluded(svc)


async def test_earlier_attempt_at_the_same_tag_is_ignored(
    sup: Supervisor, settings: Settings
) -> None:
    # A retry after a failed attempt: status.json still holds that attempt's outcome for
    # the very same tag. It must not be reported as this request's outcome.
    _install_helper(settings)
    _write_status(settings, tag="v0.5.0", state="failed", error="old", request_id="0" * 32)
    svc = _service(sup, settings)
    await svc.request("0.5.0")
    await asyncio.sleep(0.1)
    assert svc.in_progress()
    assert svc.request_file.exists()
    assert svc.view()["state"] == "pending"
    _write_status(settings, tag="v0.5.0", state="failed", error="new")
    await _concluded(svc)
    assert svc.view()["error"] == "new"


async def test_a_malformed_request_is_reported_rejected(
    sup: Supervisor, settings: Settings
) -> None:
    # The helper could not read an id from a tampered request: "rejected", no id.
    svc = _service(sup, settings)
    await svc.request("0.5.0")
    _write_status(
        settings,
        tag=None,
        state="rejected",
        finished_at="2999-01-01T00:00:00+00:00",
        request_id=None,
    )
    await _concluded(svc)
    assert svc.view()["state"] == "rejected"


async def test_stale_idless_rejection_is_ignored(sup: Supervisor, settings: Settings) -> None:
    svc = _service(sup, settings)
    _write_status(
        settings,
        tag=None,
        state="rejected",
        finished_at="2000-01-01T00:00:00+00:00",
        request_id=None,
    )
    await svc.request("0.5.0")
    await asyncio.sleep(0.1)
    assert svc.in_progress()
    _write_status(settings, tag="v0.5.0", state="failed")
    await _concluded(svc)


async def test_timeout_gives_up_and_records_interrupted(sup: Supervisor, tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path, release_api_url="https://api.test", upgrade_timeout_seconds=1.0
    )
    svc = _service(sup, settings)
    # a clock we control, so the 1 s timeout passes without waiting for it
    ticks = iter([0.0, 0.0, 5.0, 5.0, 5.0])
    svc._clock = lambda: next(ticks)
    await svc.request("0.5.0")
    await _concluded(svc)
    last = svc.view()
    assert last["state"] == "failed" and "interrupted" in last["error"]
    assert not svc.request_file.exists()


async def test_cancellation_leaves_the_pending_record(sup: Supervisor, settings: Settings) -> None:
    # The panel being stopped by the helper's restart must not look like a failure.
    svc = _service(sup, settings)
    await svc.request("0.5.0")
    await svc.stop()
    assert svc.pending_file.exists()
    assert svc.request_file.exists()
    assert not svc.last_file.exists()


# -- reconciliation on the next start ---------------------------------------------
def _seed_pending(settings: Settings, requested_at: str = "2999-01-01T00:00:00+00:00") -> None:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    (settings.state_dir / "upgrade_pending.json").write_text(
        json.dumps(
            {
                "from": "0.4.0",
                "to": "0.5.0",
                "tag": "v0.5.0",
                "request_id": "a" * 32,
                "requested_at": requested_at,
            }
        )
    )


async def test_startup_reports_success(sup: Supervisor, settings: Settings) -> None:
    svc = _service(sup, settings, current="0.5.0")
    _seed_pending(settings)
    _write_status(settings, tag="v0.5.0", state="succeeded", log_tail="ok")
    svc.start()
    await _concluded(svc)
    last = svc.view()
    assert last["state"] == "succeeded" and last["from"] == "0.4.0" and last["to"] == "0.5.0"
    assert last["error"] is None


async def test_pending_reports_pending_then_running_once_the_helper_names_it(
    sup: Supervisor, settings: Settings
) -> None:
    svc = _service(sup, settings, current="0.5.0")
    _seed_pending(settings)
    assert svc.view()["state"] == "pending"
    _write_status(settings, tag="v0.5.0", state="running", request_id="b" * 32)
    assert svc.view()["state"] == "pending"  # another request's status
    _write_status(settings, tag="v0.5.0", state="running", request_id="a" * 32)
    assert svc.view()["state"] == "running"


async def test_startup_keeps_following_a_running_helper(
    sup: Supervisor, settings: Settings
) -> None:
    # The installer restarts the panel before the helper writes its final status.
    svc = _service(sup, settings, current="0.5.0")
    _seed_pending(settings)
    _write_status(settings, tag="v0.5.0", state="running")
    svc.start()
    await asyncio.sleep(0.1)
    assert svc.view()["state"] == "running"
    _write_status(settings, tag="v0.5.0", state="succeeded")
    await _concluded(svc)
    assert svc.view()["state"] == "succeeded"


async def test_startup_past_the_timeout_keeps_following_a_running_helper(
    sup: Supervisor, settings: Settings
) -> None:
    # A slow install (a game download): the new panel starts after
    # upgrade_timeout_seconds has passed and the helper only writes "succeeded" once the
    # panel is healthy.
    svc = _service(sup, settings, current="0.5.0")
    _seed_pending(settings, requested_at="2000-01-01T00:00:00+00:00")
    _write_status(settings, tag="v0.5.0", state="running")
    svc.start()
    await asyncio.sleep(0.1)
    assert svc.view()["state"] == "running"
    _write_status(settings, tag="v0.5.0", state="succeeded")
    await _concluded(svc)
    assert svc.view()["state"] == "succeeded"


async def test_a_helper_stuck_running_is_given_up_after_the_grace(
    sup: Supervisor, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(upgrade_mod, "FOLLOW_GRACE_SECONDS", 0.2)
    svc = _service(sup, settings, current="0.5.0")
    _seed_pending(settings, requested_at="2000-01-01T00:00:00+00:00")
    _write_status(settings, tag="v0.5.0", state="running")
    svc.start()
    await _concluded(svc)
    last = svc.view()
    assert last["state"] == "failed" and "interrupted" in last["error"]


async def test_a_finished_helper_reads_as_running_until_concluded(
    sup: Supervisor, settings: Settings
) -> None:
    # Between the helper's final write and the panel's next poll, the upgrade must not
    # appear to fall back to "waiting for the helper".
    svc = _service(sup, settings, current="0.5.0")
    _seed_pending(settings)
    _write_status(settings, tag="v0.5.0", state="succeeded")
    assert svc.view()["state"] == "running"


async def test_startup_reports_failure(sup: Supervisor, settings: Settings) -> None:
    svc = _service(sup, settings)
    _seed_pending(settings)
    _write_status(settings, tag="v0.5.0", state="failed", error="installer exited 1")
    svc.start()
    await _concluded(svc)
    last = svc.view()
    assert last["state"] == "failed" and last["error"] == "installer exited 1"


async def test_reinstalling_the_running_version_succeeds(
    sup: Supervisor, settings: Settings
) -> None:
    # A hand-placed request naming the version already installed (the real-host check).
    svc = _service(sup, settings, current="0.5.0")
    (settings.state_dir / "upgrade_pending.json").write_text(
        json.dumps(
            {
                "from": "0.5.0",
                "to": "0.5.0",
                "tag": "v0.5.0",
                "request_id": "c" * 32,
                "requested_at": "2999-01-01T00:00:00+00:00",
            }
        )
    )
    _write_status(settings, tag="v0.5.0", state="succeeded", request_id="c" * 32)
    svc.start()
    await _concluded(svc)
    assert svc.view()["state"] == "succeeded"


async def test_orphaned_request_is_reported_interrupted(
    sup: Supervisor, settings: Settings
) -> None:
    svc = _service(sup, settings)
    _seed_pending(settings, requested_at="2000-01-01T00:00:00+00:00")
    svc.request_file.parent.mkdir(parents=True, exist_ok=True)
    svc.request_file.write_text(json.dumps({"tag": "v0.5.0"}))
    svc.start()
    await _concluded(svc)
    last = svc.view()
    assert last["state"] == "failed" and "interrupted" in last["error"]
    assert not svc.request_file.exists()


async def test_nothing_outstanding_starts_nothing(sup: Supervisor, settings: Settings) -> None:
    svc = _service(sup, settings)
    svc.start()
    assert svc._follow_task is None
    assert svc.view() is None


async def test_an_unreadable_pending_record_is_cleared(sup: Supervisor, settings: Settings) -> None:
    svc = _service(sup, settings)
    svc.pending_file.write_text("{nope")
    svc.start()
    await _concluded(svc)
    assert svc.view() is None


# -- startup wiring -----------------------------------------------------------------
async def test_runtime_follows_a_pending_upgrade_on_startup(tmp_path: Path) -> None:
    from xonotic_webui.runtime import Runtime

    settings = make_settings(tmp_path, upgrade_timeout_seconds=30.0)
    _seed_pending(settings)
    _write_status(settings, tag="v0.5.0", state="failed", error="boom")
    runtime = Runtime(settings)
    await runtime.startup()
    try:
        await _wait_for(lambda: not runtime.upgrade.pending_file.exists())
        assert runtime.upgrade.view()["state"] == "failed"
    finally:
        await runtime.shutdown()
