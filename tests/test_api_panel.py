"""Panel self-update routes against a live panel (panel-self-update)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from tests.conftest import Live
from xonotic_webui import __version__
from xonotic_webui.selfupdate.release_check import SCHEMA

LiveFactory = Callable[..., "asyncio.Future[Live]"]  # noqa: F821


def _seed_release(live: Live, *, latest: str, **extra: object) -> None:
    """Make the cached check report ``latest`` without contacting GitHub."""
    state = live.settings.state_dir / "release_check.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "latest": latest,
                "tag": f"v{latest}",
                "release_url": f"https://github.com/carlhako/xonotic-webui/releases/tag/v{latest}",
                "name": f"xonotic-webui {latest}",
                "published_at": "2026-10-01T00:00:00Z",
                "notes": "## Notes",
                "etag": None,
                "checked_at": "2026-10-01T00:00:01+00:00",
                "check_error": None,
                **extra,
            }
        )
    )


def _install_helper(live: Live) -> None:
    s = live.settings
    s.upgrade_helper_path.parent.mkdir(parents=True, exist_ok=True)
    s.upgrade_helper_path.write_text("#!/usr/bin/python3\n")
    s.upgrade_status_dir.mkdir(parents=True, exist_ok=True)


async def _live_with_release(live_factory: LiveFactory, latest: str) -> Live:
    """A panel whose release cache is seeded before it starts."""
    app = await live_factory()
    # The checker loads its cache at construction, so reload it from the seeded file.
    _seed_release(app, latest=latest)
    app.runtime.release_check._state = app.runtime.release_check._load()
    return app


async def test_version_reports_the_running_version_and_no_check_yet(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.get("/api/panel/version")
    assert r.status_code == 200
    body = r.json()
    assert body["current"] == __version__
    assert body["latest"] is None and body["checked_at"] is None
    assert body["update_available"] is False
    assert body["upgrade"] is None
    assert body["one_click_available"] is False


async def test_manual_command_is_present_only_without_the_helper(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        without = (await client.get("/api/panel/version")).json()
        assert without["one_click_available"] is False
        assert without["manual_command"] == (
            "curl -fsSL https://github.com/carlhako/xonotic-webui/releases/latest/download/"
            "install.sh | bash"
        )
        _install_helper(app)
        with_helper = (await client.get("/api/panel/version")).json()
        assert with_helper["one_click_available"] is True
        assert with_helper["manual_command"] is None


async def test_a_newer_cached_release_is_reported_with_its_details(live: LiveFactory) -> None:
    app = await _live_with_release(live, "99.0.0")
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        body = (await client.get("/api/panel/version")).json()
    assert body["update_available"] is True
    assert body["latest"] == "99.0.0"
    assert body["release_name"] == "xonotic-webui 99.0.0"
    assert body["notes"] == "## Notes"
    assert body["release_url"].endswith("/v99.0.0")


async def test_check_runs_a_check_and_returns_the_result(live: LiveFactory) -> None:
    app = await live()
    seen: list[int] = []

    def handle(_req: httpx.Request) -> httpx.Response:
        seen.append(1)
        return httpx.Response(
            200,
            json={
                "tag_name": "v99.0.0",
                "html_url": "https://github.com/carlhako/xonotic-webui/releases/tag/v99.0.0",
                "body": "- new",
            },
        )

    app.runtime.release_check._transport = httpx.MockTransport(handle)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.post("/api/panel/check")
        assert r.status_code == 200
        body = r.json()
        assert body["latest"] == "99.0.0" and body["update_available"] is True
        assert body["notes"] == "- new"
        assert body["checked_at"] and body["check_error"] is None
        # ...and the same result is served to everyone afterwards, without another request.
        assert (await client.get("/api/panel/version")).json()["latest"] == "99.0.0"
    assert len(seen) == 1


async def test_a_failed_check_is_reported_not_raised(live: LiveFactory) -> None:
    app = await live()

    def handle(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    app.runtime.release_check._transport = httpx.MockTransport(handle)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.post("/api/panel/check")
    assert r.status_code == 200
    assert r.json()["check_error"].startswith("release source unreachable")
    assert r.json()["update_available"] is False


async def test_upgrade_is_requested_and_reported_pending(live: LiveFactory) -> None:
    app = await _live_with_release(live, "99.0.0")
    _install_helper(app)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.post("/api/panel/upgrade", json={"version": "99.0.0"})
        assert r.status_code == 200
        body = r.json()
        assert body["upgrade"]["state"] == "pending"
        assert body["upgrade"]["from"] == __version__
        assert body["upgrade"]["to"] == "99.0.0"
        request = json.loads((app.settings.upgrade_request_dir / "request.json").read_text())
        assert request["tag"] == "v99.0.0"
        # A second request is refused while the first is outstanding.
        again = await client.post("/api/panel/upgrade", json={"version": "99.0.0"})
        assert again.status_code == 409
        assert again.json()["detail"]["code"] == "upgrade_in_progress"
        assert (await client.get("/api/panel/version")).json()["upgrade"]["state"] == "pending"


@pytest.mark.parametrize(
    ("setup", "version", "code"),
    [
        ("no_release", "99.0.0", "no_update_available"),
        ("release", "98.0.0", "version_mismatch"),
        ("release_no_helper", "99.0.0", "helper_not_installed"),
    ],
)
async def test_upgrade_refusals_carry_a_code_and_write_nothing(
    live: LiveFactory, setup: str, version: str, code: str
) -> None:
    if setup == "no_release":
        app = await live()
        _install_helper(app)
    else:
        app = await _live_with_release(live, "99.0.0")
        if setup == "release":
            _install_helper(app)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.post("/api/panel/upgrade", json={"version": version})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == code and detail["message"]
    assert not (app.settings.upgrade_request_dir / "request.json").exists()
    assert not (app.settings.state_dir / "upgrade_pending.json").exists()


async def test_upgrade_is_refused_during_a_lifecycle_transition(live: LiveFactory) -> None:
    app = await _live_with_release(live, "99.0.0")
    _install_helper(app)
    async with app.runtime.supervisor._op_lock, httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.post("/api/panel/upgrade", json={"version": "99.0.0"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "transition_in_progress"


async def test_upgrade_body_is_validated(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        assert (await client.post("/api/panel/upgrade", json={})).status_code == 422


async def test_unknown_panel_paths_are_errors_not_the_application(
    live: LiveFactory, tmp_path: Path
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "index.html").write_text("<!doctype html><title>app</title>")
    app = await live(static=bundle)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        for path in ["/api/panel", "/api/panel/nope", "/api/panel/version/extra"]:
            r = await client.get(path)
            assert r.status_code == 404, path
            assert "<title>app</title>" not in r.text
        # ...while the interface's own /panel route still loads the application.
        page = await client.get("/panel")
        assert page.status_code == 200 and "<title>app</title>" in page.text
