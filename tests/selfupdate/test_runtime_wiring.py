"""panel-self-update: the release check is scheduled without blocking startup."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from tests.helpers import make_settings
from xonotic_webui.app import create_app


def test_startup_completes_while_the_first_check_is_pending(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, release_check_enabled=True)
    started = time.monotonic()
    with TestClient(create_app(settings)) as client:
        assert time.monotonic() - started < 10  # far below the 30 s initial delay
        assert client.get("/health").status_code == 200
        checker = client.app.state.runtime.release_check
        assert checker._task is not None
        assert not checker._task.done()  # still in its initial delay
        assert checker.state.checked_at is None  # nothing contacted yet
    assert checker._task is None  # cancelled on shutdown


def test_disabled_check_makes_no_request(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        checker = client.app.state.runtime.release_check
        assert checker._task is None
        assert checker.state.checked_at is None
