"""The real panel process: SIGTERM stops the game server and leaves no orphan."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

from tests.conftest import free_port
from tests.helpers import make_game_root, process_alive

# uvicorn finishes its graceful shutdown (and our lifespan handler) and then re-raises the
# signal it caught, so a SIGTERM'd panel exits "by SIGTERM". systemd treats that as a clean
# stop for the unit. Either status means the shutdown completed.
CLEAN_EXIT = (0, -signal.SIGTERM)


def _wait_health(base: str, proc: subprocess.Popen[bytes], seconds: float = 20.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"panel exited early with {proc.returncode}")
        try:
            if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.1)
    raise AssertionError("panel did not become healthy")


def _spawn_panel(tmp_path: Path, port: int, **extra: str) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        "XONOTIC_WEBUI_HOST": "127.0.0.1",
        "XONOTIC_WEBUI_PORT": str(port),
        "XONOTIC_WEBUI_GAME_ROOT": str(make_game_root(tmp_path)),
        "XONOTIC_WEBUI_STATE_DIR": str(tmp_path / "state"),
        "XONOTIC_WEBUI_GAME_PORT": "26998",
        "XONOTIC_WEBUI_SHUTDOWN_TIMEOUT": "10",
        "XONOTIC_WEBUI_CONFIG_FILE": "/nonexistent.toml",
        **extra,
    }
    return subprocess.Popen(
        [sys.executable, "-m", "xonotic_webui"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_sigterm_stops_the_game_server_and_leaves_no_orphan(tmp_path: Path) -> None:
    port = free_port()
    panel = _spawn_panel(tmp_path, port)
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_health(base, panel)
        assert httpx.post(f"{base}/api/lifecycle/start", timeout=30).status_code == 200
        game_pid = json.loads((tmp_path / "state" / "userdir" / "fake-launch.json").read_text())[
            "pid"
        ]
        assert process_alive(game_pid)

        panel.send_signal(signal.SIGTERM)
        assert panel.wait(timeout=30) in CLEAN_EXIT

        assert not process_alive(game_pid), "the game server outlived the panel"
        # the server was running, so the intent to run is kept for the next start
        assert json.loads((tmp_path / "state" / "state.json").read_text())["desired_running"]
    finally:
        if panel.poll() is None:
            panel.kill()
            panel.wait()


def test_panel_restores_a_server_that_was_running(tmp_path: Path) -> None:
    port = free_port()
    base = f"http://127.0.0.1:{port}"

    first = _spawn_panel(tmp_path, port)
    try:
        _wait_health(base, first)
        assert httpx.post(f"{base}/api/lifecycle/start", timeout=30).status_code == 200
        first.send_signal(signal.SIGTERM)
        assert first.wait(timeout=30) in CLEAN_EXIT
    finally:
        if first.poll() is None:
            first.kill()
            first.wait()

    second = _spawn_panel(tmp_path, port)
    try:
        _wait_health(base, second)
        deadline = time.monotonic() + 20
        state = None
        while time.monotonic() < deadline:
            state = httpx.get(f"{base}/api/status", timeout=2).json()["state"]
            if state == "running":
                break
            time.sleep(0.1)
        assert state == "running"
        second.send_signal(signal.SIGTERM)
        assert second.wait(timeout=30) in CLEAN_EXIT
    finally:
        if second.poll() is None:
            second.kill()
            second.wait()
