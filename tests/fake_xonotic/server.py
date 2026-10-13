#!/usr/bin/env python3
"""A fake Xonotic dedicated server for tests (design D15).

It replays the *real* startup output captured in ``tests/fixtures/xonotic/startup.txt``
and answers the commands the panel uses with replies shaped like the real server's
(``status 1``, ``sv_eventlog``, ``quit``). It runs standalone: ``server.py -userdir D
+port P ...``, the same arguments the panel gives the real binary.

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

Test-only commands (written to stdin like any other):

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
import signal
import sys
import threading
import time
from pathlib import Path
from typing import ClassVar

HERE = Path(__file__).resolve().parent
STARTUP = HERE.parent / "fixtures" / "xonotic" / "startup.txt"

FLAGS: dict[str, str] = {}
for item in filter(None, os.environ.get("FAKE_XONOTIC", "").split(",")):
    key, _, value = item.partition("=")
    FLAGS[key.strip()] = value.strip()

out_lock = threading.Lock()


def emit(line: str) -> None:
    with out_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def flag_float(name: str, default: float = 0.0) -> float:
    return float(FLAGS[name]) if name in FLAGS else default


class State:
    map = "_init/_init"
    gametype = "dm"
    eventlog = "0" if "eventlog_off" in FLAGS else "1"
    roster: ClassVar[dict[int, dict]] = {}  # ent -> {id, bot, name}
    lock = threading.Lock()


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
    wrapper = None
    if info["serverconfig"]:
        cfg = path / "data" / info["serverconfig"]
        wrapper = cfg.read_text() if cfg.is_file() else None
    (path / "fake-launch.json").write_text(
        json.dumps({**info, "cwd": os.getcwd(), "pid": os.getpid(), "wrapper_cfg": wrapper})
    )


def startup_lines() -> list[str]:
    return STARTUP.read_text().splitlines()


def load_map(gametype: str, name: str) -> None:
    State.map = name
    State.gametype = gametype


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
    for line in lines[:first_event]:
        emit(line)
    if "noready" in FLAGS:
        return
    time.sleep(flag_float("map_delay"))
    gamestart = lines[first_event] if first_event < len(lines) else None
    # ``:gamestart:<gametype>_<map>:<id>`` -> load that map
    gametype, _, name = "dm", "", "atelier"
    if gamestart:
        target = gamestart.split(":gamestart:")[1].split(":")[0]
        gametype, _, name = target.partition("_")
    load_map(gametype, name)
    if State.eventlog == "1" and "eventlog_off" not in FLAGS:
        for line in lines[first_event:]:
            emit(line)
    crash_after = flag_float("crash_after", -1)
    if crash_after >= 0:
        threading.Timer(crash_after, lambda: os._exit(139)).start()


def status_reply() -> None:
    with State.lock:
        rows = sorted(State.roster.items())
        map_name = State.map
    maxp = "16" if map_name == "_init/_init" else "8"
    emit("^7host:     fake xonotic")
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


def handle(command: str) -> None:
    command = command.strip()
    if not command:
        return
    verb, _, rest = command.partition(" ")
    if verb == "quit":
        if "ignore_quit" in FLAGS:
            return
        time.sleep(flag_float("quit_delay"))
        emit("^7^7Player stats writing failed: -2")
        os._exit(0)
    elif verb == "status":
        status_reply()
    elif verb == "sv_eventlog" and not rest:
        emit(f'^7"sv_eventlog" is "{State.eventlog}" ["0"]')
    elif verb in ("sv_eventlog", "sv_eventlog_console") and rest:
        if "eventlog_off" not in FLAGS:
            State.eventlog = rest.strip().strip('"')
    elif verb == "fake_crash":
        os._exit(139)
    elif verb == "fake_emit":
        emit(rest)
    elif verb == "fake_map":
        gametype, _, name = rest.partition(" ")
        load_map(gametype, name)
        emit(f"^7:gamestart:{gametype}_{name}:0.1.1")
    elif verb == "fake_join":
        pid, ent, ip, name = rest.split(" ", 3)
        with State.lock:
            State.roster[int(ent)] = {"id": int(pid), "bot": ip == "bot", "name": name}
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


def main() -> None:
    record_launch(parse_args(sys.argv[1:]))
    if "ignore_term" in FLAGS:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    # Commands are queued by the pipe until startup finishes, like the real server's
    # command buffer, because the reader below only starts once startup has run.
    startup = threading.Thread(target=run_startup, daemon=True)
    startup.start()
    startup.join()
    for line in sys.stdin:
        handle(line)
    # stdin closed: a real server keeps running; the fake exits so tests never leak it.
    os._exit(0)


if __name__ == "__main__":
    main()
