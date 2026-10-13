"""Configuration for xonotic-webui.

Settings are read, in decreasing precedence, from:

1. Environment variables prefixed ``XONOTIC_WEBUI_`` (e.g. ``XONOTIC_WEBUI_PORT=8080``).
2. A TOML config file, whose path is taken from ``XONOTIC_WEBUI_CONFIG_FILE`` and
   otherwise defaults to ``/etc/xonotic-webui/xonotic-webui.toml``.
3. The documented defaults below.

Every value has a default, so the panel loads with no config file and no environment
set. The application name, environment prefix and default paths derive from the two
constants below (design D16); a rename is a change here and in ``pyproject.toml``.
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

APP_NAME = "xonotic-webui"
ENV_PREFIX = "XONOTIC_WEBUI_"

# Layout (design D5).
DEFAULT_CONFIG_FILE = Path(f"/etc/{APP_NAME}/{APP_NAME}.toml")
DEFAULT_STATE_DIR = Path(f"/var/lib/{APP_NAME}")
DEFAULT_GAME_ROOT = Path("/opt/xonotic/0.8.6")

GAME_BINARY_NAME = "xonotic-linux64-dedicated"


class _TomlConfigSource(PydanticBaseSettingsSource):
    """Loads settings from the TOML file named by ``XONOTIC_WEBUI_CONFIG_FILE``."""

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        raw_path = os.environ.get(f"{ENV_PREFIX}CONFIG_FILE")
        path = Path(raw_path) if raw_path else DEFAULT_CONFIG_FILE
        if not path.is_file():
            return {}
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        # Accept either a flat table or an ``[xonotic_webui]`` section.
        section = APP_NAME.replace("-", "_")
        if section in data and isinstance(data[section], dict):
            data = data[section]
        return {str(k).lower(): v for k, v in data.items()}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, env_file=None, extra="ignore")

    # --- Networking -----------------------------------------------------
    host: str = Field(default="0.0.0.0", description="Address the HTTP service binds to.")
    port: int = Field(
        default=80,
        ge=1,
        le=65535,
        description=(
            "Port the web interface binds to. Ports below 1024 are privileged: the shipped "
            "systemd unit grants CAP_NET_BIND_SERVICE so the panel can bind 80 as an "
            "unprivileged user."
        ),
    )
    game_port: int = Field(
        default=26000,
        ge=1,
        le=65535,
        description="UDP port the Xonotic server listens on (passed as +port).",
    )

    # --- Filesystem layout ---------------------------------------------
    game_root: Path = Field(
        default=DEFAULT_GAME_ROOT,
        description="Extracted, read-only Xonotic tree containing the dedicated binary.",
    )
    state_dir: Path = Field(
        default=DEFAULT_STATE_DIR,
        description="The panel's mutable state: state.json and the game's userdir.",
    )

    # --- Timeouts and thresholds ----------------------------------------
    shutdown_timeout: float = Field(
        default=60.0,
        ge=1.0,
        description="Seconds to wait after 'quit' before terminating the server forcibly.",
    )
    readiness_timeout: float = Field(
        default=120.0,
        ge=1.0,
        description="Seconds to wait for the server to become ready before the start fails.",
    )
    crash_restart_threshold: int = Field(
        default=3,
        ge=0,
        description=(
            "Crashes within crash_restart_window after which automatic restart is "
            "abandoned. 0 disables automatic restart entirely."
        ),
    )
    crash_restart_window: float = Field(
        default=300.0,
        ge=1.0,
        description="Sliding window, in seconds, over which crashes are counted.",
    )
    crash_restart_delay: float = Field(
        default=2.0,
        ge=0.0,
        description="Seconds to wait before an automatic restart attempt.",
    )

    console_buffer_lines: int = Field(
        default=2000,
        ge=1,
        description="Maximum console lines retained in the in-memory history buffer.",
    )

    # --- Derived paths ---------------------------------------------------
    @property
    def game_binary(self) -> Path:
        return self.game_root / GAME_BINARY_NAME

    @property
    def userdir(self) -> Path:
        """Passed as ``-userdir``; the only place the game writes (design D5)."""
        return self.state_dir / "userdir"

    @property
    def state_file(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def game_settings_file(self) -> Path:
        """The operator's server settings, as saved from the panel."""
        return self.state_dir / "settings.json"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            _TomlConfigSource(settings_cls),
            file_secret_settings,
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
