#!/usr/bin/env python3
"""Regenerate the bundled cvar catalogue from the captured ``cvarlist`` reply.

    python scripts/build_cvar_catalogue.py            # rewrite the committed file
    python scripts/build_cvar_catalogue.py --check    # exit 1 if it is out of date

The catalogue (``src/xonotic_webui/serversettings/cvars.json``) is committed;
``tests/test_cvar_catalogue.py`` fails when it differs from this script's output.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from xonotic_webui.serversettings.catalogue import (  # noqa: E402
    CATALOGUE_RESOURCE,
    build_from_cvarlist,
    dump_document,
)

SOURCE = ROOT / "tests" / "fixtures" / "xonotic" / "cvarlist.txt"
TARGET = ROOT / "src" / "xonotic_webui" / "serversettings" / CATALOGUE_RESOURCE


def render() -> str:
    return dump_document(build_from_cvarlist(SOURCE.read_text()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="only verify the committed file")
    args = parser.parse_args()
    text = render()
    if args.check:
        if not TARGET.is_file() or TARGET.read_text() != text:
            print(f"{TARGET} is out of date; run scripts/build_cvar_catalogue.py", file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(text)
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
