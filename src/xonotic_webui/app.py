"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from xonotic_webui import __version__
from xonotic_webui.api.schemas import HealthModel
from xonotic_webui.logging import configure_logging, get_logger
from xonotic_webui.runtime import Runtime
from xonotic_webui.settings import APP_NAME, Settings, get_settings
from xonotic_webui.staticfiles import SPAStaticFiles, frontend_built, static_dir

log = get_logger("app")


def create_app(settings: Settings | None = None, *, static: Path | None = None) -> FastAPI:
    configure_logging()
    settings = settings or get_settings()
    runtime = Runtime(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await runtime.startup()
        try:
            yield
        finally:
            await runtime.shutdown()

    app = FastAPI(title=APP_NAME, version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.runtime = runtime

    @app.get("/health", response_model=HealthModel, tags=["meta"])
    async def health() -> dict:
        # Independent of the game server: answers whether or not it is running.
        return {"status": "ok", "version": __version__}

    runtime.attach(app)

    directory = static or static_dir()
    if frontend_built(directory):
        app.mount("/", SPAStaticFiles(directory=directory, html=True), name="spa")
    else:
        log.warning(
            "No built frontend at %s; only the API is being served. "
            "Run `npm --prefix web run build` for the UI.",
            directory,
        )
    return app
