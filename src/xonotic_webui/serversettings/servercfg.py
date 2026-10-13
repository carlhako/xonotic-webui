"""A best-effort scan of the operator's ``server.cfg`` (design D11).

Only simple top-level assignments are recognised: ``name value``, ``set name value`` and
``seta name value``. ``exec`` lines, aliases, conditionals and anything else are not
followed, so a result means "``server.cfg`` sets this", never "this is the final value".
"""

from __future__ import annotations

from pathlib import Path

from xonotic_webui.serversettings.serialize import is_valid_name

# Commands that look like ``name value`` but are not cvar assignments.
_NOT_CVARS = frozenset(
    {
        "alias",
        "bind",
        "unbind",
        "exec",
        "echo",
        "say",
        "if",
        "else",
        "defer",
        "wait",
        "map",
        "changelevel",
        "restart",
        "kick",
        "ban",
        "sv_cmd",
        "rcon",
        "cvar_changes",
        "cvar_lockdefaults",
        "cvar_resettodefaults_all",
        "cvar_resettodefaults_nosaveonly",
        "cvar_resettodefaults_saveonly",
        "cvar_resettodefaults",
        "toggle",
        "cycle",
        "freeze",
    }
)


def _first_token(text: str) -> tuple[str, str]:
    """The first console token of ``text`` (quotes removed) and the rest of the line."""
    text = text.lstrip()
    if text.startswith('"'):
        end = text.find('"', 1)
        if end == -1:
            return text[1:], ""
        return text[1:end], text[end + 1 :]
    parts = text.split(None, 1)
    if not parts:
        return "", ""
    return parts[0], parts[1] if len(parts) > 1 else ""


def _strip_comment(line: str) -> str:
    in_quote = False
    for i, char in enumerate(line):
        if char == '"':
            in_quote = not in_quote
        elif not in_quote and line.startswith("//", i):
            return line[:i]
    return line


def scan_server_cfg_text(text: str) -> dict[str, str]:
    """Cvar names (lower-cased) to the last value ``text`` assigns them."""
    found: dict[str, str] = {}
    for raw in text.splitlines():
        line = _strip_comment(raw).strip()
        if not line:
            continue
        verb, rest = _first_token(line)
        if verb.lower() in ("set", "seta"):
            name, rest = _first_token(rest)
        else:
            name = verb
        lowered = name.lower()
        if not name or lowered in _NOT_CVARS or not is_valid_name(name):
            continue
        if ";" in _outside_quotes(rest):
            rest = rest[: rest.index(";")]
        value, _ = _first_token(rest)
        if not rest.strip():
            continue  # a bare name only reads the cvar
        found[lowered] = value
    return found


def _outside_quotes(text: str) -> str:
    out: list[str] = []
    in_quote = False
    for char in text:
        if char == '"':
            in_quote = not in_quote
        elif not in_quote:
            out.append(char)
    return "".join(out)


def scan_server_cfg(path: Path) -> dict[str, str]:
    """Scan the file at ``path``; a missing or unreadable file gives an empty result."""
    try:
        return scan_server_cfg_text(path.read_text(errors="replace"))
    except OSError:
        return {}
