#!/usr/bin/env python3
"""A fake Xonotic dedicated server for tests (design D15).

It replays the *real* startup output captured in ``tests/fixtures/xonotic/startup.txt``
and answers the commands the panel uses with replies shaped like the real server's
(``status 1``, ``sv_eventlog``, cvar reads and writes, ``gametype``, ``gotomap``,
``endmatch``, ``pause``, ``quit``). It runs standalone: ``server.py -userdir D +port P ...``,
the same arguments the panel gives the real binary.

Behaviour is selected by ``FAKE_XONOTIC`` (comma separated ``key`` or ``key=value``):

    startup_delay=S   sleep S seconds before the startup output
    map_delay=S       seconds between "Switching to map" and the map being loaded
    noready           print startup but never load a map (a server that hangs starting)
    exit_early=N      exit with status N before becoming ready
    crash_after=S     exit 139 S seconds after becoming ready
    eventlog_off      emit no event-log lines (readiness only via ``status``); the
                      event-log cvar stays 0 and refuses to be changed
    ignore_quit       ignore ``quit``
    ignore_term       ignore SIGTERM (only SIGKILL stops it)
    quit_delay=S      take S seconds to exit after ``quit``
    autopause_delay=S seconds after a map loads until an empty server with ``sv_autopause 1``
                      pauses itself (the real server uses 5, which is the default here)
    scoreboard_delay=S  seconds the scoreboard shows when a human is connected (real: 5)
    vote_delay=S      extra seconds the map vote takes at a normal match end with a human
    endmatch_delay=S  seconds from ``:gameover`` to the map switch with nobody connected
    maps_file=PATH    JSON ``{map: [gametype, ...]}`` of the installed maps
                      (default: ``maps.json`` beside this file)

Cvars are the ones in the captured ``cvarlist.txt`` with their real defaults. Console
parsing follows what the spike observed: ``;`` outside quotes separates commands, ``//``
outside quotes starts a comment, ``$$`` is a literal ``$`` and ``$name`` expands, even
inside quotes, before the command is split into arguments.

Test-only commands (written to stdin like any other, never parsed as console commands):

    fake_join <id> <ent> <bot|ip> <raw name>   print a :join: line and add to the roster
    fake_silent_join <ent> <bot|ip> <raw name> add to the roster without logging it
    fake_name <id> <raw name>                  print a :name: line
    fake_part <id>                             print a :part: line and drop from roster
    fake_map <gametype> <map>                  print a :gamestart: line
    fake_emit <raw line>                       print a line verbatim
    fake_crash                                 exit 139 immediately
"""

from __future__ import annotations

import json
import os
import re
import signal
import sys
import threading
import time
from pathlib import Path
from typing import ClassVar

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "fixtures" / "xonotic"
STARTUP = FIXTURES / "startup.txt"
CVARLIST = FIXTURES / "cvarlist.txt"

FLAGS: dict[str, str] = {}
for item in filter(None, os.environ.get("FAKE_XONOTIC", "").split(",")):
    key, _, value = item.partition("=")
    FLAGS[key.strip()] = value.strip()

out_lock = threading.Lock()

PRE_MAP = "_init/_init"

# Gametype id -> the cvar that selects it (in the game's own order of precedence).
GAMETYPE_CVARS: dict[str, str] = {
    "dm": "g_dm",
    "tdm": "g_tdm",
    "ctf": "g_ctf",
    "ca": "g_ca",
    "ft": "g_freezetag",
    "kh": "g_keyhunt",
    "ka": "g_keepaway",
    "tka": "g_tka",
    "ons": "g_onslaught",
    "as": "g_assault",
    "dom": "g_domination",
    "duel": "g_duel",
    "lms": "g_lms",
    "nb": "g_nexball",
    "rc": "g_race",
    "cts": "g_cts",
    "inv": "g_invasion",
    "surv": "g_survival",
    "mayhem": "g_mayhem",
    "tmayhem": "g_tmayhem",
}
MUTATOR_CVARS = {
    "instagib": "g_instagib",
    "nix": "g_nix",
    "vampire": "g_vampire",
    "jetpack": "g_jetpack",
    "pinata": "g_pinata",
    "midair": "g_midair",
    "walljump": "g_walljump",
    "cloaked": "g_cloaked",
    "touchexplode": "g_touchexplode",
    "dodging": "g_dodging",
    "norecoil": "g_norecoil",
}

_CVAR_LINE = re.compile(r'^(?:\^7)?(\S+) is "(.*?)" \["(.*?)"\](?: .*)?$')
_VAR_NAME = re.compile(r"[A-Za-z0-9_.]+")


def emit(line: str) -> None:
    with out_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def flag_float(name: str, default: float = 0.0) -> float:
    return float(FLAGS[name]) if name in FLAGS else default


class State:
    map = PRE_MAP
    gametype = "dm"
    roster: ClassVar[dict[int, dict]] = {}  # ent -> {id, bot, name}
    # lower-cased name -> [display name, value, default or None]
    cvars: ClassVar[dict[str, list]] = {}
    maps: ClassVar[dict[str, list[str]]] = {}
    paused = False
    queued: ClassVar[list] = []
    ending = False
    match_no = 0
    applied_maxplayers = "16"
    autopause_timer: threading.Timer | None = None
    userdir: Path | None = None
    info: ClassVar[dict] = {}
    lock = threading.RLock()


# --------------------------------------------------------------------------- cvars
def load_cvars() -> None:
    for line in CVARLIST.read_text().splitlines():
        m = _CVAR_LINE.match(line)
        if m is not None:
            name, _value, default = m.groups()
            # The capture was taken with settings applied: start from the defaults.
            State.cvars[name.lower()] = [name, default, default]
    # ``maxplayers`` is not in the cvar list and has no default part when read back.
    State.cvars["maxplayers"] = ["maxplayers", "16", None]
    State.cvars["hostname"][1] = "fake xonotic"
    State.cvars["sv_eventlog"][1] = "0" if "eventlog_off" in FLAGS else "1"
    State.cvars["sv_eventlog_console"][1] = State.cvars["sv_eventlog"][1]


def load_maps() -> None:
    path = Path(FLAGS["maps_file"]) if "maps_file" in FLAGS else HERE / "maps.json"
    State.maps = {k: list(v) for k, v in json.loads(path.read_text()).items()}


def cv(name: str, default: str = "") -> str:
    entry = State.cvars.get(name.lower())
    return entry[1] if entry is not None else default


def cv_int(name: str, default: int = 0) -> int:
    try:
        return int(float(cv(name, str(default))))
    except ValueError:
        return default


def set_cvar(name: str, value: str, *, create: bool = False) -> bool:
    key = name.lower()
    if key in ("sv_eventlog", "sv_eventlog_console") and "eventlog_off" in FLAGS:
        return True  # refused, as before
    entry = State.cvars.get(key)
    if entry is None:
        if not create:
            return False
        State.cvars[key] = [name, value, ""]
        return True
    entry[1] = value
    return True


def print_cvar(name: str) -> None:
    display, value, default = State.cvars[name.lower()]
    suffix = "" if default is None else f' ["{default}"]'
    emit(f'^7"{display}" is "{value}"{suffix}')


# ----------------------------------------------------------------- console parsing
def split_commands(line: str) -> list[str]:
    """Split a console line at ``;`` outside quotes; ``//`` outside quotes ends it."""
    parts: list[str] = []
    cur: list[str] = []
    quoted = False
    i = 0
    while i < len(line):
        c = line[i]
        if quoted:
            if c == "\\" and i + 1 < len(line) and line[i + 1] in '"\\':
                cur.append(line[i : i + 2])
                i += 2
                continue
            if c == '"':
                quoted = False
            cur.append(c)
        elif c == '"':
            quoted = True
            cur.append(c)
        elif c == ";":
            parts.append("".join(cur))
            cur = []
        elif line.startswith("//", i):
            break
        else:
            cur.append(c)
        i += 1
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def expand(command: str) -> str:
    """``$$`` -> ``$`` and ``$name`` -> the cvar's value, quoted or not."""
    out: list[str] = []
    i = 0
    while i < len(command):
        c = command[i]
        if c != "$":
            out.append(c)
            i += 1
        elif command.startswith("$$", i):
            out.append("$")
            i += 2
        else:
            m = _VAR_NAME.match(command, i + 1)
            if m is None:
                out.append(c)
                i += 1
            else:
                name = m.group(0)
                if name.lower() in State.cvars:
                    out.append(cv(name))
                else:
                    emit(f"^7Warning: Could not expand ${name}")
                    out.append("$" + name)
                i = m.end()
    return "".join(out)


def tokenize(command: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    n = len(command)
    while i < n:
        while i < n and command[i].isspace():
            i += 1
        if i >= n:
            break
        if command[i] == '"':
            i += 1
            buf: list[str] = []
            while i < n and command[i] != '"':
                if command[i] == "\\" and i + 1 < n and command[i + 1] in '"\\':
                    buf.append(command[i + 1])
                    i += 2
                    continue
                buf.append(command[i])
                i += 1
            i += 1
            tokens.append("".join(buf))
        else:
            j = i
            while j < n and not command[j].isspace():
                j += 1
            tokens.append(command[i:j])
            i = j
    return tokens


# ------------------------------------------------------------------------- launch
def parse_args(argv: list[str]) -> dict:
    info: dict = {"argv": argv, "userdir": None, "port": None, "serverconfig": None}
    it = iter(range(len(argv)))
    for i in it:
        if argv[i] == "-userdir":
            info["userdir"] = argv[i + 1]
        elif argv[i] == "+port":
            info["port"] = argv[i + 1]
        elif argv[i] == "+serverconfig":
            info["serverconfig"] = argv[i + 1]
    return info


def record_launch(info: dict) -> None:
    userdir = info["userdir"]
    if not userdir:
        return
    path = Path(userdir)
    path.mkdir(parents=True, exist_ok=True)
    State.userdir = path
    wrapper = None
    if info["serverconfig"]:
        cfg = path / "data" / info["serverconfig"]
        wrapper = cfg.read_text() if cfg.is_file() else None
    configs = {p.name: p.read_text() for p in sorted((path / "data").glob("*.cfg"))}
    (path / "fake-launch.json").write_text(
        json.dumps(
            {
                **info,
                "cwd": os.getcwd(),
                "pid": os.getpid(),
                "wrapper_cfg": wrapper,
                "configs": configs,
            }
        )
    )


def startup_lines() -> list[str]:
    return STARTUP.read_text().splitlines()


# --------------------------------------------------------------------- map and match
def supports(map_name: str, gametype: str) -> bool:
    return gametype in State.maps.get(map_name, [])


def selected_gametype() -> str:
    for gametype, cvar in GAMETYPE_CVARS.items():
        if cv(cvar) == "1":
            return gametype
    return "dm"


def candidates(gametype: str) -> list[str]:
    listed = [m for m in cv("g_maplist").split() if supports(m, gametype)]
    return listed or sorted(m for m in State.maps if supports(m, gametype))


def rotation_next(current: str, gametype: str) -> str:
    pool = candidates(gametype)
    if not pool:
        return current
    if current in pool:
        return pool[(pool.index(current) + 1) % len(pool)]
    return pool[0]


def mutator_list() -> list[str]:
    names = [m for m, cvar in MUTATOR_CVARS.items() if m != "norecoil" and cv(cvar) == "1"]
    if cv(MUTATOR_CVARS["norecoil"]) == "1":
        names.append("norecoil")
    return names


def apply_map_settings(gametype: str) -> None:
    """At every map load the map's settings reset the limits (overrides win)."""
    time_override = cv_int("timelimit_override", -1)
    set_cvar("timelimit", str(time_override if time_override >= 0 else 15))
    per_gametype = cv_int(f"g_{gametype}_point_limit", -1)
    frag_override = cv_int("fraglimit_override", -1)
    if per_gametype >= 0:
        frags = per_gametype
    elif frag_override >= 0:
        frags = frag_override
    else:
        frags = 30
    set_cvar("fraglimit", str(frags))
    lead_override = cv_int("leadlimit_override", -1)
    set_cvar("leadlimit", str(lead_override if lead_override >= 0 else 0))
    capture_override = cv_int("capturelimit_override", -1)
    set_cvar("capturelimit", str(capture_override if capture_override >= 0 else 10))


def humans() -> int:
    with State.lock:
        return sum(1 for p in State.roster.values() if not p["bot"])


def announce_match() -> None:
    State.match_no += 1
    match_id = f"0.{int(time.time())}.{State.match_no:06d}"
    if cv("sv_eventlog") == "1" and "eventlog_off" not in FLAGS:
        emit(f"^7:gamestart:{State.gametype}_{State.map}:{match_id}")
        emit(f"^7:gameinfo:mutators:LIST:{':'.join(mutator_list())}")
        emit("^7:gameinfo:end")


def load_map(name: str, *, apply_maxplayers: bool = False, announce: bool = True) -> None:
    gametype = selected_gametype()
    if name in State.maps and not supports(name, gametype):
        emit(
            "^7^7can't play the selected map in the given game mode "
            f"({gametype}). Falling back to a supported mode (dm)."
        )
        gametype = "dm" if supports(name, "dm") else State.maps[name][0]
    with State.lock:
        State.map = name
        State.gametype = gametype
        State.ending = False
        if apply_maxplayers:
            State.applied_maxplayers = cv("maxplayers", "16")
    apply_map_settings(gametype)
    if not cv("g_maplist").strip():
        set_cvar("g_maplist", " ".join(candidates(gametype)))
    arm_autopause()
    if announce:
        announce_match()


def arm_autopause() -> None:
    with State.lock:
        if State.autopause_timer is not None:
            State.autopause_timer.cancel()
            State.autopause_timer = None
        State.paused = False
        State.queued = []
        if cv("sv_autopause") != "1" or humans() > 0:
            return
        timer = threading.Timer(flag_float("autopause_delay", 5.0), _autopause_now)
        timer.daemon = True
        State.autopause_timer = timer
        timer.start()


def _autopause_now() -> None:
    with State.lock:
        if cv("sv_autopause") == "1" and humans() == 0 and State.map != PRE_MAP:
            State.paused = True  # silent, as the real server


def run_deferred(action) -> None:
    """Run ``action`` now, or when the server is next unpaused (frames do not run)."""
    with State.lock:
        if State.paused:
            State.queued.append(action)
            return
    action()


def unpause() -> list:
    with State.lock:
        State.paused = False
        queued, State.queued = State.queued, []
    return queued


def pause_name() -> str:
    return cv("sv_adminnick") or cv("hostname")


def begin_end_match() -> None:
    with State.lock:
        if State.ending or State.map == PRE_MAP:
            return
        State.ending = True
        gametype, name = State.gametype, State.map
    emit(f"^7:scores:{gametype}_{name}:7")
    emit("^7:labels:player:score!!,,kills,deaths<")
    emit("^7:end")
    emit("^7:gameover")
    threading.Thread(target=finish_match, args=(humans() > 0,), daemon=True).start()


def finish_match(had_humans: bool) -> None:
    if had_humans:
        time.sleep(flag_float("scoreboard_delay", 5.0))
        if not cv("nextmap"):
            time.sleep(flag_float("vote_delay", 0.0))
    else:
        time.sleep(flag_float("endmatch_delay", 0.1))
    if cv("g_playerstats_gamereport_uri"):
        emit("^7^7uri_multi_ready: got HTTP error 422, data is in unusable format - not continuing")
        emit("^7^7Player stats writing failed: -422")
    nxt = cv("nextmap")
    if nxt not in State.maps:
        nxt = rotation_next(State.map, State.gametype)
    set_cvar("nextmap", "")
    emit(f"^7^7Switching to map {nxt}")
    time.sleep(flag_float("map_delay"))
    load_map(nxt)


# ---------------------------------------------------------------------- commands
def status_reply() -> None:
    with State.lock:
        rows = sorted(State.roster.items())
        map_name = State.map
        maxp = State.applied_maxplayers if map_name != PRE_MAP else "16"
    emit(f"^7host:     {cv('hostname')}")
    emit("^7version:  Xonotic build 03:14:05 Jun 20 2023 - release (gamename Xonotic)")
    emit("^7protocol: 3504 (DP7)")
    emit(f"^7map:      {map_name}")
    emit("^7timing:   0.0% CPU, 0.00% lost, offset avg 0.0ms, max 0.0ms, sdev 0.0ms")
    emit(f"^7players:  {len(rows)} active ({maxp} max)")
    emit("^7")
    emit("^7^2IP" + " " * 45 + "%pl ping  time   frags  no   name")
    for ent, p in rows:
        ip = "botclient" if p["bot"] else "127.0.0.1:50000"
        emit(f"^7^3{ip:<44}   0   20  0:00:10    0  #{ent}   ^7{p['name']}")


def cmd_gametype(args: list[str]) -> None:
    if not args:
        emit("^7^7Incorrect parameters for ^2gametype^7")
        emit("^7^7Usage:^3 sv_cmd gametype <mode>")
        emit("^7^7  Where <mode> is the gametype mode to switch to.")
        emit("^7^7See also: ^2gotomap^7")
        return
    wanted = args[0]
    if wanted not in GAMETYPE_CVARS:
        emit(f"^7Failed to switch to {wanted}: this game type does not exist!")
        return
    if not any(supports(m, wanted) for m in State.maps):
        emit(f"^7Failed to switch to {wanted}: no map supports this game type!")
        return
    for gametype, cvar in GAMETYPE_CVARS.items():
        set_cvar(cvar, "1" if gametype == wanted else "0")
    emit(f"^7Game type successfully switched to {wanted}")


def cmd_gotomap(args: list[str]) -> None:
    if not args:
        emit("^7^7Incorrect parameters for ^2gotomap^7")
        emit("^7^7Usage:^3 sv_cmd gotomap <map>")
        return
    name = args[0]
    if not supports(name, selected_gametype()):
        emit("^7^7The map you suggested is not available on this server.")
        return
    set_cvar("nextmap", name)
    emit("^7^7Map switch will happen after scoreboard.")
    run_deferred(begin_end_match)


def cmd_pause() -> None:
    with State.lock:
        was_paused = State.paused
    if was_paused:
        queued = unpause()
        emit(f"^7{pause_name()} unpaused the game")
        for action in queued:
            action()
    else:
        with State.lock:
            State.paused = True
        emit(f"^7{pause_name()} paused the game")


def cmd_maxplayers(args: list[str], startup: bool) -> None:
    if not args:
        print_cvar("maxplayers")
        return
    set_cvar("maxplayers", args[0])
    if State.map != PRE_MAP and not startup:
        emit("^7maxplayers can not be changed while a server is running.")
        emit('^7It will be changed on next server startup ("map" command).')
        emit(f'^7"maxplayers" set to "{args[0]}"')
    elif State.map == PRE_MAP:
        State.applied_maxplayers = args[0]


def cmd_changelevel(name: str, *, with_map_command: bool) -> None:
    if name not in State.maps:
        emit(f'^7^7Couldn\'t load map "{name}"')
        return
    load_map(name, apply_maxplayers=with_map_command)


def cmd_exec(args: list[str]) -> None:
    if not args or State.userdir is None:
        return
    path = State.userdir / "data" / args[0]
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        execute(line, startup=True)


def run(args: list[str], startup: bool) -> None:
    if not args:
        return
    verb, rest = args[0].lower(), args[1:]
    if verb == "quit":
        if "ignore_quit" in FLAGS:
            return
        time.sleep(flag_float("quit_delay"))
        emit("^7^7Player stats writing failed: -2")
        os._exit(0)
    elif verb == "status":
        status_reply()
    elif verb == "echo":
        emit("^7" + " ".join(rest))
    elif verb in ("set", "seta"):
        if len(rest) >= 2:
            set_cvar(rest[0], rest[1], create=True)
    elif verb == "maxplayers":
        cmd_maxplayers(rest, startup)
    elif verb == "gametype":
        cmd_gametype(rest)
    elif verb == "gotomap":
        cmd_gotomap(rest)
    elif verb in ("endmatch", "_endmatch"):
        run_deferred(begin_end_match)
    elif verb == "restart":
        if State.map != PRE_MAP:
            load_map(State.map)
    elif verb == "resetmatch":
        emit("^7^3Match is restarting...")
        emit("^7:restart")
    elif verb == "changelevel" and rest:
        cmd_changelevel(rest[0], with_map_command=False)
    elif verb == "map" and rest:
        cmd_changelevel(rest[0], with_map_command=True)
    elif verb == "pause":
        cmd_pause()
    elif verb == "exec":
        cmd_exec(rest)
    elif verb in State.cvars:
        if rest:
            set_cvar(verb, rest[0])
        else:
            print_cvar(verb)
    else:
        emit(f'^7Unknown command "{args[0]}"')


def execute(line: str, *, startup: bool = False) -> None:
    line = line.strip()
    if not line:
        return
    verb, _, rest = line.partition(" ")
    if verb.startswith("fake_"):
        fake_command(verb, rest)
        return
    for command in split_commands(line):
        run(tokenize(expand(command)), startup)


def fake_command(verb: str, rest: str) -> None:
    if verb == "fake_crash":
        os._exit(139)
    elif verb == "fake_emit":
        emit(rest)
    elif verb == "fake_map":
        gametype, _, name = rest.partition(" ")
        with State.lock:
            State.map, State.gametype, State.ending = name, gametype, False
        emit(f"^7:gamestart:{gametype}_{name}:0.1.1")
    elif verb == "fake_join":
        pid, ent, ip, name = rest.split(" ", 3)
        with State.lock:
            State.roster[int(ent)] = {"id": int(pid), "bot": ip == "bot", "name": name}
        if ip != "bot":
            for action in unpause():  # the first player joining unpauses the server
                action()
        emit(f"^7:join:{pid}:{ent}:{ip}:{name}")
    elif verb == "fake_silent_join":
        ent, ip, name = rest.split(" ", 2)
        with State.lock:
            State.roster[int(ent)] = {"id": 0, "bot": ip == "bot", "name": name}
    elif verb == "fake_name":
        pid, name = rest.split(" ", 1)
        with State.lock:
            for p in State.roster.values():
                if p["id"] == int(pid):
                    p["name"] = name
        emit(f"^7:name:{pid}:{name}")
    elif verb == "fake_part":
        with State.lock:
            for ent in [e for e, p in State.roster.items() if p["id"] == int(rest)]:
                del State.roster[ent]
        emit(f"^7:part:{rest}")
    else:
        emit(f'^7Unknown command "{verb}"')


# ------------------------------------------------------------------------- startup
def initial_map(default: str) -> str:
    gametype = selected_gametype()
    listed = [m for m in cv("g_maplist").split() if supports(m, gametype)]
    if listed:
        return listed[0]
    if supports(default, gametype) or default not in State.maps:
        return default
    pool = candidates(gametype)
    return pool[0] if pool else default


def run_startup() -> None:
    delay = flag_float("startup_delay")
    if delay:
        time.sleep(delay)
    if "exit_early" in FLAGS:
        for line in startup_lines()[:6]:
            emit(line)
        emit("^7Fatal: simulated startup failure")
        os._exit(int(FLAGS["exit_early"] or 1))
    lines = startup_lines()
    # Everything up to and including the first event-log line is "startup".
    first_event = next((i for i, line in enumerate(lines) if ":gamestart:" in line), len(lines))
    switching = next(
        (i for i, line in enumerate(lines[:first_event]) if "Switching to map" in line), None
    )
    gamestart = lines[first_event] if first_event < len(lines) else None
    # ``:gamestart:<gametype>_<map>:<id>`` -> the map the capture loaded
    default_map = "atelier"
    if gamestart:
        default_map = gamestart.split(":gamestart:")[1].split(":")[0].partition("_")[2]

    emit_to = switching if switching is not None else first_event
    for line in lines[:emit_to]:
        emit(line)
    if "noready" in FLAGS:
        return
    # The wrapper's ``exec`` lines have already been printed by the capture; run them now.
    serverconfig = State.info.get("serverconfig")
    if serverconfig:
        cmd_exec([serverconfig])
    name = initial_map(default_map)
    if switching is not None:
        emit(f"^7^7Switching to map {name}")
        for line in lines[switching + 1 : first_event]:
            emit(line)
    else:
        for line in lines[emit_to:first_event]:
            emit(line)
    time.sleep(flag_float("map_delay"))
    load_map(name, apply_maxplayers=True)
    crash_after = flag_float("crash_after", -1)
    if crash_after >= 0:
        threading.Timer(crash_after, lambda: os._exit(139)).start()


def main() -> None:
    info = parse_args(sys.argv[1:])
    State.info = info
    record_launch(info)
    load_cvars()
    load_maps()
    if "ignore_term" in FLAGS:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    # Commands are queued by the pipe until startup finishes, like the real server's
    # command buffer, because the reader below only starts once startup has run.
    startup = threading.Thread(target=run_startup, daemon=True)
    startup.start()
    startup.join()
    for line in sys.stdin:
        execute(line)
    # stdin closed: a real server keeps running; the fake exits so tests never leak it.
    os._exit(0)


if __name__ == "__main__":
    main()
