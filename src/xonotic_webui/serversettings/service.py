"""Saving settings, applying them to a running server and reading live values.

Saving always writes the store and regenerates the config, whether or not the server is
running; a running server also gets each change as an ordinary console line (echoed into
the console history like an operator command, design D2). The result tells the operator
when each change takes effect.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from xonotic_webui.colors import strip_leading_codes
from xonotic_webui.console.console import Console, InternalQueryError
from xonotic_webui.logging import get_logger
from xonotic_webui.serversettings.catalogue import CatalogueEntry, CvarCatalogue, load_catalogue
from xonotic_webui.serversettings.registry import (
    CURATED,
    CURATED_BY_KEY,
    ApplyClass,
    CuratedSetting,
    is_reserved,
)
from xonotic_webui.serversettings.serialize import (
    InvalidCvarNameError,
    InvalidValueError,
    assignment,
    is_valid_name,
    validate_name,
    validate_value,
)
from xonotic_webui.serversettings.servercfg import scan_server_cfg
from xonotic_webui.serversettings.store import (
    SettingsStore,
    StoreData,
    render_settings_cfg,
)
from xonotic_webui.settings import Settings
from xonotic_webui.supervisor import (
    SETTINGS_CONFIG_NAME,
    NotRunningError,
    RunState,
    Supervisor,
    write_userdir_config,
)

log = get_logger("serversettings")

MapGametypes = Mapping[str, frozenset[str]]

# One live query line stays well inside the console's command-length bound.
_QUERY_LINE_CHARS = 900
_DEFAULT_QUERY_TIMEOUT = 5.0

_IS_WITH_DEFAULT = re.compile(r'^"(?P<name>[^"]+)" is "(?P<value>.*)" \["(?P<default>.*)"\]\s*$')
_IS_NO_DEFAULT = re.compile(r'^"(?P<name>[^"]+)" is "(?P<value>.*)"\s*$')
_UNKNOWN = re.compile(r'^Unknown command "(?P<name>[^"]+)"\s*$')


class SettingsError(ValueError):
    """A rejected settings request. ``code`` is stable; ``field`` names the culprit."""

    code = "invalid_setting"

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class UnknownSettingError(SettingsError):
    code = "unknown_setting"


class ReservedCvarError(SettingsError):
    code = "reserved_cvar"


class InvalidOverrideNameError(SettingsError):
    code = "invalid_cvar_name"


@dataclass(frozen=True)
class SettingState:
    setting: CuratedSetting
    value: Any  # the saved value, or ``None`` when the default applies
    live_value: str | None
    server_cfg: bool


@dataclass(frozen=True)
class OverrideState:
    name: str
    value: str
    live_value: str | None
    server_cfg: bool


@dataclass(frozen=True)
class CvarState:
    entry: CatalogueEntry
    live_value: str | None
    override: str | None
    server_cfg: bool


@dataclass(frozen=True)
class CvarPage:
    total: int
    offset: int
    limit: int
    items: list[CvarState]


class CvarValueCollector:
    """Collects one ``"name" is "value" ["default"]`` or ``Unknown command "name"`` per name.

    Matching is on the line with only its leading colour reset removed, so a colour code
    inside a value reaches the caller intact.
    """

    def __init__(self, names: Iterable[str]) -> None:
        self._expected = {n.lower() for n in names}
        self.values: dict[str, str | None] = {}

    @property
    def done(self) -> bool:
        return len(self.values) >= len(self._expected)

    def feed(self, raw_line: str) -> bool:
        if self.done:
            return False
        text = strip_leading_codes(raw_line).rstrip("\r")
        for pattern in (_IS_WITH_DEFAULT, _IS_NO_DEFAULT):
            m = pattern.match(text)
            if m is not None:
                return self._take(m.group("name"), m.group("value"))
        m = _UNKNOWN.match(text)
        if m is not None:
            return self._take(m.group("name"), None)
        return False

    def _take(self, name: str, value: str | None) -> bool:
        key = name.lower()
        if key not in self._expected or key in self.values:
            return False
        self.values[key] = value
        return True


def apply_class_for(setting: CuratedSetting, value: Any, *, running: bool) -> ApplyClass:
    """When saving ``value`` (``None`` resets to the default) takes effect."""
    if not running:
        return ApplyClass.NEXT_START
    if setting.live_cvar is not None:
        # The plain cvar changes the current match, but going back to "map default" can
        # only be honoured when the next map loads (design D3).
        return ApplyClass.NOW if value is not None and value >= 0 else ApplyClass.NEXT_MAP
    return setting.apply


def coerce(setting: CuratedSetting, value: Any) -> Any:
    """Validate and normalise ``value`` for ``setting`` or raise :class:`SettingsError`."""

    def fail(message: str) -> SettingsError:
        return SettingsError(message, field=setting.key)

    kind = setting.kind
    if kind == "bool":
        if not isinstance(value, bool):
            raise fail(f"{setting.label} must be on or off")
        return value
    if kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise fail(f"{setting.label} must be a number")
        if kind == "int":
            if isinstance(value, float):
                if not value.is_integer():
                    raise fail(f"{setting.label} must be a whole number")
                value = int(value)
        else:
            value = float(value)
        low, high = setting.min, setting.max
        if (low is not None and value < low) or (high is not None and value > high):
            raise fail(f"{setting.label} must be between {_num(low)} and {_num(high)}")
        return value
    if kind == "choice":
        if value not in {c.value for c in setting.choices}:
            allowed = ", ".join(c.value for c in setting.choices)
            raise fail(f"{setting.label} must be one of: {allowed}")
        return value
    if not isinstance(value, str):
        raise fail(f"{setting.label} must be text")
    if setting.max_length is not None and len(value) > setting.max_length:
        raise fail(f"{setting.label} must be at most {setting.max_length} characters")
    try:
        return validate_value(value)
    except InvalidValueError as exc:
        raise fail(f"{setting.label}: {exc}") from exc


def _num(value: float | None) -> str:
    if value is None:
        return "any"
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


class ServerSettingsService:
    def __init__(
        self,
        settings: Settings,
        supervisor: Supervisor,
        console: Console,
        store: SettingsStore,
        *,
        map_gametypes: Callable[[], MapGametypes | None] | None = None,
        catalogue: CvarCatalogue | None = None,
        query_timeout: float = _DEFAULT_QUERY_TIMEOUT,
    ) -> None:
        self._settings = settings
        self._sup = supervisor
        self._console = console
        self._store = store
        self._map_gametypes = map_gametypes
        self._catalogue = catalogue
        self._query_timeout = query_timeout
        self._live_lock = asyncio.Lock()

    # -- the store and the generated config ---------------------------------------------
    @property
    def store(self) -> SettingsStore:
        return self._store

    @property
    def catalogue(self) -> CvarCatalogue:
        if self._catalogue is None:
            self._catalogue = load_catalogue()
        return self._catalogue

    @property
    def running(self) -> bool:
        return self._sup.state is RunState.RUNNING

    def load(self) -> StoreData:
        return self._store.load()

    def render_config(self) -> str:
        gametypes = self._map_gametypes() if self._map_gametypes is not None else None
        return render_settings_cfg(self._store.load(), gametypes)

    def write_config(self) -> None:
        """Regenerate ``userdir/data/<APP_NAME>-settings.cfg`` from the store."""
        write_userdir_config(self._settings, SETTINGS_CONFIG_NAME, self.render_config())

    def server_cfg_values(self) -> dict[str, str]:
        """What ``server.cfg`` assigns, from the first copy the game would find."""
        for base in (self._settings.userdir / "data", self._settings.game_root / "data"):
            path = base / "server.cfg"
            if path.is_file():
                return scan_server_cfg(path)
        return {}

    async def update(self, mutate: Callable[[StoreData], None]) -> StoreData:
        """Load the store, apply ``mutate``, save it and regenerate the config."""
        data = self._store.load()
        mutate(data)
        self._store.save(data)
        self.write_config()
        return data

    # -- reading ---------------------------------------------------------------------------
    async def view(self) -> list[SettingState]:
        data = self._store.load()
        server_cfg = self.server_cfg_values()
        live = await self._live_or_empty([s.read_cvar for s in CURATED])
        return [
            SettingState(
                setting=s,
                value=data.values.get(s.key),
                live_value=live.get(s.read_cvar.lower()),
                server_cfg=s.key.lower() in server_cfg
                or (s.live_cvar is not None and s.live_cvar.lower() in server_cfg),
            )
            for s in CURATED
        ]

    async def live_values(self, names: Iterable[str]) -> dict[str, str | None]:
        """Current values of ``names`` from the running server, keyed lower-case.

        A name the game does not know maps to ``None``. One panel query is sent per few
        dozen names (design D5) and its reply is withheld from the console stream.
        Raises :class:`NotRunningError` when the server is not running and
        :class:`InternalQueryError` when it does not answer in time.
        """
        wanted = list(dict.fromkeys(n for n in names if is_valid_name(n)))
        values: dict[str, str | None] = {}
        async with self._live_lock:
            for chunk in _chunks(wanted):
                collector = CvarValueCollector(chunk)
                await self._console.query(
                    ";".join(chunk), collector, reply_timeout=self._query_timeout
                )
                values.update(collector.values)
        return values

    async def _live_or_empty(self, names: Iterable[str]) -> dict[str, str | None]:
        """:meth:`live_values` for views: no live values is "unknown", never an error."""
        if not self.running:
            return {}
        try:
            return await self.live_values(names)
        except (NotRunningError, InternalQueryError) as exc:
            log.warning("live cvar values unavailable: %s", exc)
            return {}

    # -- curated settings --------------------------------------------------------------
    async def patch(self, changes: Mapping[str, Any]) -> dict[str, ApplyClass]:
        """Apply a partial update; ``None`` resets a setting to its default.

        Everything is validated before anything is saved. Returns each key's apply class.
        """
        if not changes:
            raise SettingsError("no settings were given")
        prepared: dict[str, Any] = {}
        for key, raw in changes.items():
            setting = CURATED_BY_KEY.get(key)
            if setting is None:
                raise UnknownSettingError(f"unknown setting {key!r}", field=key)
            prepared[key] = None if raw is None else coerce(setting, raw)

        def mutate(data: StoreData) -> None:
            for key, value in prepared.items():
                if value is None:
                    data.values.pop(key, None)
                else:
                    data.values[key] = value

        await self.update(mutate)

        commands: list[str] = []
        server_cfg = self.server_cfg_values() if self.running else {}
        for key, value in prepared.items():
            setting = CURATED_BY_KEY[key]
            if value is None:
                # Back to what the server would use after a restart: what server.cfg
                # sets, otherwise the game's default.
                text = server_cfg.get(key.lower(), setting.wire(setting.default))
                try:
                    commands.append(assignment(key, text))
                except (InvalidValueError, InvalidCvarNameError):
                    log.warning("not sending %s: server.cfg's value is not a plain value", key)
                continue
            commands.append(assignment(key, setting.wire(value)))
            if setting.live_cvar is not None and value >= 0:
                commands.append(assignment(setting.live_cvar, setting.wire(value)))
        delivered = await self.send_live(commands)
        return {
            key: apply_class_for(CURATED_BY_KEY[key], value, running=delivered)
            for key, value in prepared.items()
        }

    async def send_live(self, commands: Iterable[str]) -> bool:
        """Send ``commands`` to the running server, echoed in the console.

        Returns whether the server received them (``False`` when it is not running).
        """
        commands = list(commands)
        if not commands:
            return self.running
        if not self.running:
            return False
        try:
            for command in commands:
                await self._console.submit_command(command)
        except NotRunningError:
            return False
        return True

    # -- raw overrides ---------------------------------------------------------------
    def _check_override_name(self, name: str) -> str:
        try:
            validate_name(name)
        except InvalidCvarNameError as exc:
            raise InvalidOverrideNameError(str(exc), field=name) from exc
        if is_reserved(name):
            raise ReservedCvarError(
                f"{name} is reserved: the panel depends on it and does not allow overriding it",
                field=name,
            )
        return name

    async def overrides(self) -> list[OverrideState]:
        data = self._store.load()
        server_cfg = self.server_cfg_values()
        live = await self._live_or_empty(data.overrides)
        return [
            OverrideState(
                name=name,
                value=data.overrides[name],
                live_value=live.get(name.lower()),
                server_cfg=name.lower() in server_cfg,
            )
            for name in sorted(data.overrides)
        ]

    async def put_override(self, name: str, value: str) -> ApplyClass:
        self._check_override_name(name)
        try:
            validate_value(value)
        except InvalidValueError as exc:
            raise SettingsError(str(exc), field=name) from exc

        def mutate(data: StoreData) -> None:
            data.overrides[name] = value

        await self.update(mutate)
        delivered = await self.send_live([assignment(name, value, create=True)])
        return ApplyClass.MAY_NEED_RESTART if delivered else ApplyClass.NEXT_START

    async def delete_override(self, name: str) -> ApplyClass:
        self._check_override_name(name)

        def mutate(data: StoreData) -> None:
            data.overrides.pop(name, None)

        await self.update(mutate)
        # The running server keeps its current value until it next starts.
        return ApplyClass.NEXT_START

    # -- the catalogue ------------------------------------------------------------------
    async def search_cvars(self, query: str, offset: int = 0, limit: int = 50) -> CvarPage:
        total, entries = self.catalogue.search(query, offset, limit)
        data = self._store.load()
        server_cfg = self.server_cfg_values()
        live = await self._live_or_empty(e.name for e in entries)
        lowered = {k.lower(): v for k, v in data.overrides.items()}
        return CvarPage(
            total=total,
            offset=max(0, offset),
            limit=limit,
            items=[
                CvarState(
                    entry=e,
                    live_value=live.get(e.name.lower()),
                    override=lowered.get(e.name.lower()),
                    server_cfg=e.name.lower() in server_cfg,
                )
                for e in entries
            ],
        )


def _chunks(names: list[str]) -> Iterable[list[str]]:
    chunk: list[str] = []
    size = 0
    for name in names:
        if chunk and size + len(name) + 1 > _QUERY_LINE_CHARS:
            yield chunk
            chunk, size = [], 0
        chunk.append(name)
        size += len(name) + 1
    if chunk:
        yield chunk
