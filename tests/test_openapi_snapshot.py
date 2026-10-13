"""The committed OpenAPI schema (the front end's type source) must match the app."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "export_openapi.py"
SNAPSHOT = ROOT / "web" / "openapi.json"


def _load_exporter():
    spec = importlib.util.spec_from_file_location("export_openapi", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_snapshot_matches_the_application() -> None:
    exporter = _load_exporter()
    current = exporter.render(exporter.build_schema())
    committed = SNAPSHOT.read_text()
    assert committed == current, (
        "web/openapi.json is stale: routes or models changed. "
        "Run `python scripts/export_openapi.py` and commit the result."
    )


def test_snapshot_documents_every_route_the_interface_uses() -> None:
    paths = set(json.loads(SNAPSHOT.read_text())["paths"])
    assert {
        "/health",
        "/api/lifecycle/start",
        "/api/lifecycle/stop",
        "/api/lifecycle/restart",
        "/api/console/stream",
        "/api/console/command",
        "/api/status",
        "/api/status/stream",
    } <= paths


def test_detects_drift(tmp_path: Path) -> None:
    exporter = _load_exporter()
    schema = exporter.build_schema()
    schema["paths"]["/api/invented"] = {}
    assert exporter.render(schema) != SNAPSHOT.read_text()
