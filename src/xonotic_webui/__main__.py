"""Console entrypoint: ``xonotic-webui`` / ``python -m xonotic_webui``."""

from __future__ import annotations

import sys

import uvicorn

from xonotic_webui.logging import configure_logging
from xonotic_webui.settings import get_settings

# uvicorn.run's own status for a server that never started.
_STARTUP_FAILURE = 3

# Open SSE connections would otherwise hold the shutdown open indefinitely; this bounds
# how long uvicorn waits for them before cancelling, after which the lifespan handler
# stops the game server (itself bounded by SHUTDOWN_TIMEOUT). The systemd unit's
# TimeoutStopSec must exceed the sum (see deploy/xonotic-webui.service).
GRACEFUL_SHUTDOWN_SECONDS = 10


def main() -> None:
    configure_logging()
    settings = get_settings()
    config = uvicorn.Config(
        "xonotic_webui.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_config=None,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
    )
    server = uvicorn.Server(config)
    server.run()
    if not server.started:
        sys.exit(_STARTUP_FAILURE)


if __name__ == "__main__":
    main()
