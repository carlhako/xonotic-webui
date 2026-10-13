"""HTTP API against a live server and the fake dedicated server."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from tests.conftest import Live

LiveFactory = Callable[..., "asyncio.Future[Live]"]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    def apply(spec: str) -> None:
        monkeypatch.setenv("FAKE_XONOTIC", spec)

    return apply


async def sse_events(
    client: httpx.AsyncClient, path: str, *, until: Callable[[dict], bool], timeout: float = 10.0
) -> list[dict]:
    seen: list[dict] = []
    async with client.stream("GET", path) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        async with asyncio.timeout(timeout):
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    seen.append(event)
                    if until(event):
                        break
    return seen


# --- 3.3 health -------------------------------------------------------------------


async def test_health_reports_version_while_the_game_server_is_stopped(live: LiveFactory) -> None:
    from xonotic_webui import __version__

    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "version": __version__}
        status = (await client.get("/api/status")).json()
        assert status["state"] == "stopped"  # health did not need it running


# --- 7.1 lifecycle ------------------------------------------------------------------


async def test_start_stop_restart_success(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        r = await client.post("/api/lifecycle/start")
        assert r.status_code == 200
        assert r.json()["state"] == "running"

        r = await client.post("/api/lifecycle/restart")
        assert r.status_code == 200
        assert r.json()["state"] == "running"

        r = await client.post("/api/lifecycle/stop")
        assert r.status_code == 200
        assert r.json()["state"] == "stopped"


async def test_rejections_carry_precise_codes(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        r = await client.post("/api/lifecycle/stop")
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "not_running"

        await client.post("/api/lifecycle/start")
        r = await client.post("/api/lifecycle/start")
        assert r.status_code == 409
        assert r.json()["detail"] == {
            "code": "already_running",
            "message": "the server is already running",
        }
        await client.post("/api/lifecycle/stop")


async def test_transition_in_progress_is_a_409(
    live: LiveFactory, fake: Callable[[str], None]
) -> None:
    fake("startup_delay=1.0")
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        starting = asyncio.create_task(client.post("/api/lifecycle/start"))
        for _ in range(100):
            if (await client.get("/api/status")).json()["state"] == "starting":
                break
            await asyncio.sleep(0.02)
        r = await client.post("/api/lifecycle/restart")
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "transition_in_progress"
        assert (await starting).status_code == 200
        await client.post("/api/lifecycle/stop")


async def test_game_not_installed_is_503(live: LiveFactory, tmp_path: Path) -> None:
    app = await live(game_root=tmp_path / "nothing-here")
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.post("/api/lifecycle/start")
        assert r.status_code == 503
        assert r.json()["detail"]["code"] == "game_not_installed"
        assert (await client.get("/api/status")).json()["state"] == "stopped"


async def test_startup_failures_are_reported_with_the_reason(
    live: LiveFactory, fake: Callable[[str], None]
) -> None:
    fake("exit_early=3")
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        r = await client.post("/api/lifecycle/start")
        assert r.status_code == 502
        assert r.json()["detail"]["code"] == "start_failed"
        assert "status 3" in r.json()["detail"]["message"]
        status = (await client.get("/api/status")).json()
        assert status["state"] == "stopped"
        assert status["last_start_failure"]["exit_code"] == 3


async def test_readiness_timeout_is_504(live: LiveFactory, fake: Callable[[str], None]) -> None:
    fake("noready")
    app = await live(readiness_timeout=1.0)
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        r = await client.post("/api/lifecycle/start")
        assert r.status_code == 504
        assert r.json()["detail"]["code"] == "readiness_timeout"


# --- 7.2 console and status ----------------------------------------------------------------


async def test_command_validation_and_state(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        r = await client.post("/api/console/command", json={"command": "status 1"})
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "not_running"

        await client.post("/api/lifecycle/start")
        for bad in ["", "   ", "a\nb"]:
            r = await client.post("/api/console/command", json={"command": bad})
            assert r.status_code == 422, bad
            assert r.json()["detail"]["code"] == "invalid_command"
        r = await client.post("/api/console/command", json={"command": "fake_emit ^7ok"})
        assert r.status_code == 204
        await client.post("/api/lifecycle/stop")


async def test_end_to_end_start_see_output_send_command_stop(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        assert (await client.post("/api/lifecycle/start")).status_code == 200

        async def send() -> None:
            await asyncio.sleep(0.3)
            r = await client.post("/api/console/command", json={"command": "fake_emit ^7e2e-pong"})
            assert r.status_code == 204

        driver = asyncio.create_task(send())
        events = await sse_events(
            client, "/api/console/stream", until=lambda e: e["plain"] == "e2e-pong"
        )
        await driver

        kinds = {e["kind"] for e in events}
        assert "output" in kinds and "command" in kinds
        first = events[0]
        assert set(first) == {"seq", "kind", "text", "plain"}
        assert events[-1]["text"] == "^7e2e-pong"  # raw colour codes preserved
        seqs = [e["seq"] for e in events]
        assert seqs == sorted(set(seqs))

        r = await client.post("/api/lifecycle/stop")
        assert r.json()["state"] == "stopped"


async def test_status_stream_snapshot_then_live_changes(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        assert (await client.post("/api/lifecycle/start")).status_code == 200

        async def join() -> None:
            await asyncio.sleep(0.3)
            await client.post(
                "/api/console/command", json={"command": "fake_join 1 1 127.0.0.1 ^1Red^7"}
            )

        driver = asyncio.create_task(join())
        events = await sse_events(
            client, "/api/status/stream", until=lambda e: len(e["players"]) == 1
        )
        await driver
        assert events[0]["state"] == "running"  # the snapshot on connect
        last = events[-1]
        assert last["human_count"] == 1 and last["bot_count"] == 0
        assert last["players"][0]["plain_name"] == "Red"
        assert last["map"] == "atelier" and last["gametype"] == "dm"
        await client.post("/api/lifecycle/stop")


async def test_stream_subscriptions_are_released_on_disconnect(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        await client.post("/api/lifecycle/start")
        await sse_events(client, "/api/status/stream", until=lambda e: True)
        await sse_events(client, "/api/console/stream", until=lambda e: True)

        async def released() -> bool:
            for _ in range(100):
                if (
                    app.runtime.status.subscriber_count == 0
                    and app.runtime.console.subscriber_count == 0
                ):
                    return True
                await asyncio.sleep(0.05)
            return False

        assert await released()
        await client.post("/api/lifecycle/stop")


# --- 3.4 static serving ---------------------------------------------------------------------


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>app</title><div id=root></div>")
    (root / "assets" / "app.js").write_text("console.log('hi')")
    return root


async def test_root_and_deep_links_serve_the_application(live: LiveFactory, bundle: Path) -> None:
    app = await live(static=bundle)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        for path in ["/", "/console", "/some/deep/route"]:
            r = await client.get(path)
            assert r.status_code == 200, path
            assert "<title>app</title>" in r.text
            assert r.headers["cache-control"] == "no-cache"
        assert (await client.get("/assets/app.js")).text == "console.log('hi')"


async def test_api_paths_are_not_shadowed_by_the_application(
    live: LiveFactory, bundle: Path
) -> None:
    app = await live(static=bundle)
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        for path in ["/api/does-not-exist", "/api/lifecycle/nope", "/health/nope"]:
            r = await client.get(path)
            assert r.status_code == 404, path
            assert "<title>app</title>" not in r.text
        assert (await client.get("/health")).json()["status"] == "ok"
        assert (await client.get("/api/status")).status_code == 200


async def test_without_a_bundle_only_the_api_is_served(live: LiveFactory, tmp_path: Path) -> None:
    app = await live(static=tmp_path / "empty")
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        assert (await client.get("/")).status_code == 404
        assert (await client.get("/health")).status_code == 200
