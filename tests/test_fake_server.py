"""The fake dedicated server runs standalone and speaks the real server's shapes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.helpers import FAKE_SERVER
from xonotic_webui.events import GameStart, StatusReplyCollector, parse_event


def run_fake(tmp_path: Path, stdin: str, **env: str) -> list[str]:
    import os

    proc = subprocess.run(
        [sys.executable, str(FAKE_SERVER), "-userdir", str(tmp_path / "ud"), "+port", "26000"],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, **env},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.splitlines()


def test_startup_replays_the_real_capture_through_readiness(tmp_path: Path) -> None:
    lines = run_fake(tmp_path, "quit\n")
    starts = [e for line in lines if isinstance(e := parse_event(line), GameStart)]
    assert len(starts) == 1
    assert lines[0].startswith("Game is Xonotic")


def test_status_reply_parses_with_the_real_parser(tmp_path: Path) -> None:
    lines = run_fake(
        tmp_path,
        "fake_join 1 1 127.0.0.1 ^1Red^7Name\nfake_join 2 2 bot [BOT]x\nstatus 1\nquit\n",
    )
    collector = StatusReplyCollector()
    for line in lines:
        collector.feed(line)
    assert collector.done
    assert [(r.ent, r.bot) for r in collector.rows] == [(1, False), (2, True)]


def test_quit_exits_zero_and_unknown_commands_are_reported(tmp_path: Path) -> None:
    lines = run_fake(tmp_path, "nonsense\nquit\n")
    assert any('Unknown command "nonsense"' in line for line in lines)


def test_eventlog_off_prints_no_gamestart(tmp_path: Path) -> None:
    lines = run_fake(tmp_path, "sv_eventlog 1\nsv_eventlog\nquit\n", FAKE_XONOTIC="eventlog_off")
    assert not any(isinstance(parse_event(line), GameStart) for line in lines)
    assert any('"sv_eventlog" is "0"' in line for line in lines)  # re-assert is refused
