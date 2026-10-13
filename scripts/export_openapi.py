#!/usr/bin/env python3
"""Write the API's OpenAPI schema to ``web/openapi.json``.

The front end generates its TypeScript types from this file, and
``tests/test_openapi_snapshot.py`` fails when it is stale. Run after changing a route or a
model:

    python scripts/export_openapi.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "web" / "openapi.json"


def build_schema() -> dict:
    from xonotic_webui.app import create_app
    from xonotic_webui.settings import Settings

    # Settings never affect the schema; point at a scratch dir so nothing is created.
    scratch = Path(tempfile.mkdtemp(prefix="xonotic-webui-openapi-"))
    app = create_app(Settings(state_dir=scratch, game_root=scratch), static=scratch / "none")
    return app.openapi()


def render(schema: dict) -> str:
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> int:
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(render(build_schema()))
    print(f"wrote {SNAPSHOT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
