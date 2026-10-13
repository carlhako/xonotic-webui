from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
import uvicorn

from tests.helpers import make_settings
from xonotic_webui.app import create_app
from xonotic_webui.runtime import Runtime
from xonotic_webui.settings import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The suite never reads the developer's real environment or /etc config."""
    for key in list(os.environ):
        if key.startswith(("XONOTIC_WEBUI_", "FAKE_XONOTIC")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XONOTIC_WEBUI_CONFIG_FILE", "/nonexistent/xonotic-webui.toml")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@dataclass
class Live:
    base_url: str
    runtime: Runtime
    settings: Settings


@pytest.fixture
async def live(tmp_path: Path) -> AsyncIterator[Callable[..., asyncio.Future]]:
    """Factory that serves the real app on a real socket (SSE needs one)."""
    servers: list[tuple[uvicorn.Server, asyncio.Task]] = []

    async def start(*, static: Path | None = None, **overrides: object) -> Live:
        settings = make_settings(tmp_path, **overrides)
        app = create_app(settings, static=static)
        port = free_port()
        config = uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"
        )
        server = uvicorn.Server(config)
        task = asyncio.create_task(server.serve())
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.025)
        assert server.started
        servers.append((server, task))
        return Live(f"http://127.0.0.1:{port}", app.state.runtime, settings)

    yield start  # type: ignore[misc]
    for server, task in servers:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=30)
