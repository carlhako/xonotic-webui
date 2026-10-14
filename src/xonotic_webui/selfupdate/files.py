"""Small durable-file helpers shared by the self-update modules."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` so a reader never sees a partial file.

    A temp file in the same directory, flushed and fsynced, then ``os.replace``d into
    place. The temp name differs from ``path``, so a path unit watching ``path`` does not
    fire before the content is complete.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        # mkstemp creates 0600; the helper (root) and the panel's own later runs read
        # these, and nothing in them is secret.
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read_json(path: Path) -> dict | None:
    """The object stored at ``path``; ``None`` if missing, unreadable or not an object."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_json(path: Path, data: dict) -> None:
    atomic_write_text(path, json.dumps(data))
