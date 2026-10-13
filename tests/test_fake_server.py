"""The fake dedicated server runs standalone and speaks the real server's shapes."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.helpers import FAKE_SERVER
from xonotic_webui.events import GameStart, StatusReplyCollector, parse_event


def run_fake(tmp_path: Path, stdin: str, **env: str) -> list[str]:
    proc = subprocess.run(
        [sys.executable, str(FAKE_SERVER), "-userdir", str(tmp_path / "ud"), "+port", "26000"],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, **env},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.splitlines()


def test_startup_replays_the_real_capture_through_readiness(tmp_path: Path) -> None:
    lines = run_fake(tmp_path, "quit\n")
    starts = [e for line in lines if isinstance(e := parse_event(line), GameStart)]
    assert len(starts) == 1
    assert lines[0].startswith("Game is Xonotic")


def test_status_reply_parses_with_the_real_parser(tmp_path: Path) -> None:
    lines = run_fake(
        tmp_path,
        "fake_join 1 1 127.0.0.1 ^1Red^7Name\nfake_join 2 2 bot [BOT]x\nstatus 1\nquit\n",
    )
    collector = StatusReplyCollector()
    for line in lines:
        collector.feed(line)
    assert collector.done
    assert [(r.ent, r.bot) for r in collector.rows] == [(1, False), (2, True)]


def test_quit_exits_zero_and_unknown_commands_are_reported(tmp_path: Path) -> None:
    lines = run_fake(tmp_path, "nonsense\nquit\n")
    assert any('Unknown command "nonsense"' in line for line in lines)


def test_eventlog_off_prints_no_gamestart(tmp_path: Path) -> None:
    lines = run_fake(tmp_path, "sv_eventlog 1\nsv_eventlog\nquit\n", FAKE_XONOTIC="eventlog_off")
    assert not any(isinstance(parse_event(line), GameStart) for line in lines)
    assert any('"sv_eventlog" is "0"' in line for line in lines)  # re-assert is refused


# --- group 1: the cvar store, maps and gametypes, match end and auto-pause -----------

TRANSCRIPTS = Path(__file__).parent / "fixtures" / "xonotic" / "transcripts"


def real_lines(name: str) -> set[str]:
    """The server lines in a captured transcript, without their timestamps."""
    lines: set[str] = set()
    for raw in (TRANSCRIPTS / name).read_text().splitlines():
        if raw.startswith("#") or not raw.strip():
            continue
        _, _, text = raw.strip().partition(" ")
        if not text.startswith(">>> "):
            lines.add(text)
    return lines


class Session:
    """A fake server driven interactively: send commands, wait for output."""

    def __init__(self, tmp_path: Path, *, flags: str = "", settings_cfg: str | None = None):
        userdir = tmp_path / "ud"
        data = userdir / "data"
        data.mkdir(parents=True)
        wrapper = "exec server.cfg\n"
        if settings_cfg is not None:
            (data / "xonotic-webui-settings.cfg").write_text(settings_cfg)
            wrapper += "exec xonotic-webui-settings.cfg\n"
        wrapper += "sv_eventlog 1\nsv_eventlog_console 1\n"
        (data / "xonotic-webui.cfg").write_text(wrapper)
        env = {**os.environ, "FAKE_XONOTIC": flags}
        self.proc = subprocess.Popen(
            [
                sys.executable,
                str(FAKE_SERVER),
                "-userdir",
                str(userdir),
                "+port",
                "26000",
                "+serverconfig",
                "xonotic-webui.cfg",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            env=env,
        )
        self.lines: list[str] = []
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        self.wait_for(":gameinfo:end")

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.lines.append(line.rstrip("\n"))

    def send(self, command: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()

    def wait_for(self, text: str, *, after: int = 0, timeout: float = 5.0) -> int:
        """Index of the first line at or after ``after`` containing ``text``."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for i in range(after, len(self.lines)):
                if text in self.lines[i]:
                    return i
            time.sleep(0.01)
        raise AssertionError(f"{text!r} not seen; output was:\n" + "\n".join(self.lines[-30:]))

    def ask(self, command: str, *, timeout: float = 5.0) -> list[str]:
        """Send ``command`` followed by a marker echo; the lines in between."""
        start = len(self.lines)
        marker = f"MARK{start}"
        self.send(command)
        self.send(f"echo {marker}")
        end = self.wait_for(marker, after=start, timeout=timeout)
        return self.lines[start:end]

    def count(self, text: str) -> int:
        return sum(1 for line in self.lines if text in line)

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(timeout=5)
        self._reader.join(timeout=5)
        for stream in (self.proc.stdin, self.proc.stdout):
            if stream is not None:
                stream.close()


@pytest.fixture
def session(tmp_path: Path) -> Callable[..., Session]:
    made: list[Session] = []

    def factory(**kwargs: object) -> Session:
        s = Session(tmp_path / f"s{len(made)}", **kwargs)  # type: ignore[arg-type]
        made.append(s)
        return s

    yield factory  # type: ignore[misc]
    for s in made:
        s.close()


def test_cvar_read_reply_has_value_and_default_but_not_for_maxplayers(
    session: Callable[..., Session],
) -> None:
    s = session()
    assert s.ask("timelimit_override") == ['^7"timelimit_override" is "-1" ["-1"]']
    assert s.ask("maxplayers") == ['^7"maxplayers" is "16"']
    assert s.ask("nosuchcvar") == ['^7Unknown command "nosuchcvar"']
    # the shapes are the real server's
    seen = real_lines("cvars_gametype_gotomap_paused.txt")
    assert '^7"timelimit_override" is "-1" ["-1"]' in seen
    assert '^7"maxplayers" is "16"' in seen


def test_assignment_forms(session: Callable[..., Session]) -> None:
    s = session()
    assert s.ask('hostname "live rename"') == []
    assert s.ask("hostname") == ['^7"hostname" is "live rename" ["Xonotic 0.8.6 Server"]']
    s.ask('set webui_new "x y"')
    assert s.ask("webui_new") == ['^7"webui_new" is "x y" [""]']
    # an unquoted value is cut at the first space (value_escaping transcript)
    s.ask("set webui_t5 cfg ok")
    assert s.ask("webui_t5") == ['^7"webui_t5" is "cfg" [""]']
    assert '^7"webui_t5" is "cfg" ["cfg"]' in real_lines("value_escaping_maxplayers_mutators.txt")


def test_semicolon_dollar_and_comment_rules_match_the_real_console(
    session: Callable[..., Session],
) -> None:
    s = session()
    # inside quotes ';' and '//' are literal, '$$' is '$', '$name' expands, \" is a quote
    s.ask('set webui_s1 "live a;echo INJECTED_LIVE"')
    assert s.ask("webui_s1") == ['^7"webui_s1" is "live a;echo INJECTED_LIVE" [""]']
    s.ask('set webui_s2 "live $hostname"')
    assert s.ask("webui_s2") == ['^7"webui_s2" is "live fake xonotic" [""]']
    s.ask('set webui_s3 "live $$x"')
    assert s.ask("webui_s3") == ['^7"webui_s3" is "live $x" [""]']
    s.ask('set webui_s4 "live // comment"')
    assert s.ask("webui_s4") == ['^7"webui_s4" is "live // comment" [""]']
    s.ask('set webui_s5 "q\\"q"')
    assert s.ask("webui_s5") == ['^7"webui_s5" is "q"q" [""]']
    assert not any("INJECTED" in line and "webui_s1" not in line for line in s.lines)
    # outside quotes ';' separates commands and '//' ends the line
    assert s.ask("echo one;echo two // echo three") == ["^7one", "^7two"]
    real = real_lines("value_escaping_maxplayers_mutators.txt")
    assert '^7"webui_s3" is "live $x" ["live $x"]' in real
    assert '^7"webui_s4" is "live // comment" ["live // comment"]' in real


def test_settings_cfg_is_executed_between_server_cfg_and_the_forced_cvars(
    session: Callable[..., Session],
) -> None:
    s = session(settings_cfg='hostname "from settings cfg"\nsv_motd "cfg a;echo NOPE"\n')
    assert s.ask("hostname") == ['^7"hostname" is "from settings cfg" ["Xonotic 0.8.6 Server"]']
    assert s.ask("sv_motd") == ['^7"sv_motd" is "cfg a;echo NOPE" [""]']
    assert "^7NOPE" not in s.lines  # `echo NOPE` was part of the value, never executed


def test_gametype_switch_and_failure_replies(session: Callable[..., Session]) -> None:
    s = session()
    assert s.ask("gametype tdm") == ["^7Game type successfully switched to tdm"]
    assert s.ask("gametype nosuch") == [
        "^7Failed to switch to nosuch: this game type does not exist!"
    ]
    usage = s.ask("gametype")
    assert usage[0] == "^7^7Incorrect parameters for ^2gametype^7"
    assert "^7^7Usage:^3 sv_cmd gametype <mode>" in usage
    seen = real_lines("cvars_gametype_gotomap_paused.txt")
    assert "^7Game type successfully switched to tdm" in seen
    assert "^7Failed to switch to nosuch: this game type does not exist!" in seen
    # the switch is recorded in the g_<id> cvars and applies at the next map
    assert s.ask("g_tdm") == ['^7"g_tdm" is "1" ["0"]']
    assert s.ask("g_dm") == ['^7"g_dm" is "0" ["1"]']


def test_changelevel_and_restart_emit_gamestart_and_apply_limit_overrides(
    session: Callable[..., Session],
) -> None:
    s = session()
    s.ask("gametype tdm")
    s.ask("fraglimit_override 7")
    s.ask("timelimit_override 3")
    s.send("changelevel stormkeep")
    s.wait_for(":gamestart:tdm_stormkeep:")
    assert s.ask("timelimit") == ['^7"timelimit" is "3" ["0"]']
    assert s.ask("fraglimit") == ['^7"fraglimit" is "7" ["0"]']
    # a per-gametype limit outranks the generic override, applied on the reload
    s.ask("g_tdm_point_limit 12")
    before = s.count(":gamestart:")
    s.send("restart")
    s.wait_for(":gamestart:tdm_stormkeep:", after=len(s.lines) - 1)
    assert s.count(":gamestart:") == before + 1
    assert s.ask("fraglimit") == ['^7"fraglimit" is "12" ["0"]']
    # an unsupported map for the gametype falls back to dm, with the real warning
    s.ask("gametype ctf")
    s.send("changelevel warfare")
    s.wait_for(":gamestart:dm_warfare:")
    warning = (
        "^7^7can't play the selected map in the given game mode (ctf). "
        "Falling back to a supported mode (dm)."
    )
    assert warning in s.lines
    assert warning in real_lines("changelevel_overrides_gametype.txt")


def test_mutators_apply_at_the_next_map(session: Callable[..., Session]) -> None:
    s = session()
    s.ask("g_instagib 1")
    s.send("changelevel boil")
    s.wait_for(":gameinfo:mutators:LIST:instagib:norecoil")
    assert "^7:gameinfo:mutators:LIST:instagib:norecoil" in real_lines(
        "value_escaping_maxplayers_mutators.txt"
    )


def test_maxplayers_is_refused_while_running_and_applied_by_map(
    session: Callable[..., Session],
) -> None:
    s = session()
    refusal = s.ask("maxplayers 6")
    assert refusal == [
        "^7maxplayers can not be changed while a server is running.",
        '^7It will be changed on next server startup ("map" command).',
        '^7"maxplayers" set to "6"',
    ]
    assert set(refusal) <= real_lines("value_escaping_maxplayers_mutators.txt")
    s.send("changelevel boil")
    s.wait_for(":gamestart:dm_boil:")
    assert any("(16 max)" in line for line in s.ask("status"))
    s.send("map stormkeep")
    s.wait_for(":gamestart:dm_stormkeep:")
    assert any("(6 max)" in line for line in s.ask("status"))


_TDM_ROTATION = (
    'hostname "from settings cfg"\n'
    "g_dm 0\ng_tdm 1\n"
    'g_maplist "stormkeep boil warfare"\n'
    "g_maplist_shuffle 0\n"
    "sv_autopause 0\n"
)


def test_match_end_follows_the_rotation_and_emits_the_real_sequence(
    session: Callable[..., Session],
) -> None:
    s = session(settings_cfg=_TDM_ROTATION, flags="endmatch_delay=0.05")
    assert s.count(":gamestart:tdm_stormkeep:") == 1  # first map of the list, as g_tdm 1
    start = len(s.lines)
    s.send("endmatch")
    s.wait_for(":gamestart:tdm_boil:", after=start)
    block = s.lines[start:]
    kinds = [line.split(":")[1] if line.startswith("^7:") else line for line in block]
    assert kinds.index("scores") < kinds.index("end") < kinds.index("gameover")
    assert "^7^7Switching to map boil" in block
    real = real_lines("generated_settings_cfg_unpaused.txt")
    assert "^7:gameover" in real and "^7^7Switching to map boil" in real


def test_gotomap_replies_and_switches_without_a_vote(session: Callable[..., Session]) -> None:
    s = session(settings_cfg=_TDM_ROTATION, flags="endmatch_delay=0.05")
    assert s.ask("gotomap catharsis") == [
        "^7^7The map you suggested is not available on this server."
    ]
    assert s.ask("gotomap") != []
    start = len(s.lines)
    s.send("gotomap warfare")
    s.wait_for("Map switch will happen after scoreboard.", after=start)
    s.wait_for(":gamestart:tdm_warfare:", after=start)
    assert "^7^7Switching to map warfare" in s.lines[start:]
    real = real_lines("cvars_gametype_gotomap_paused.txt") | real_lines(
        "generated_settings_cfg_unpaused.txt"
    )
    assert "^7^7Map switch will happen after scoreboard." in real
    assert "^7^7The map you suggested is not available on this server." in real


def test_the_scoreboard_only_delays_the_switch_while_a_human_is_connected(
    session: Callable[..., Session],
) -> None:
    s = session(settings_cfg=_TDM_ROTATION, flags="endmatch_delay=0.05,scoreboard_delay=0.6")
    t0 = time.monotonic()
    s.send("endmatch")
    s.wait_for(":gamestart:tdm_boil:")
    assert time.monotonic() - t0 < 0.5  # nobody connected: no scoreboard wait

    s.send("fake_join 1 1 127.0.0.1 Human")
    s.wait_for(":join:1:1:")
    t1 = time.monotonic()
    s.send("endmatch")
    s.wait_for(":gamestart:tdm_warfare:")
    assert time.monotonic() - t1 >= 0.6


def test_auto_pause_stalls_endmatch_until_a_console_pause_toggle(
    session: Callable[..., Session],
) -> None:
    s = session(
        settings_cfg=_TDM_ROTATION.replace("sv_autopause 0\n", ""),
        flags="autopause_delay=0.2,endmatch_delay=0.05",
    )
    time.sleep(0.5)  # the empty server has paused itself, silently
    assert s.count("paused the game") == 0
    s.send("endmatch")
    time.sleep(0.4)
    assert s.count(":gameover") == 0  # accepted, but nothing happens while paused

    start = len(s.lines)
    s.send("pause")
    s.wait_for("from settings cfg unpaused the game", after=start)
    s.wait_for(":gamestart:tdm_boil:", after=start)
    real = real_lines("autopause_unpause_actions.txt")
    assert "^7from settings cfg unpaused the game" in real
    assert "^7from settings cfg paused the game" in real

    # the new map re-arms the auto-pause: gotomap's reply is immediate, the switch is not
    time.sleep(0.5)
    start = len(s.lines)
    s.send("gotomap warfare")
    s.wait_for("Map switch will happen after scoreboard.", after=start)
    time.sleep(0.3)
    assert s.count("Switching to map warfare") == 0
    s.send("pause")
    s.wait_for(":gamestart:tdm_warfare:", after=start)


def test_pause_toggles_a_running_server_and_reports_each_state(
    session: Callable[..., Session],
) -> None:
    s = session(settings_cfg=_TDM_ROTATION)  # sv_autopause 0: never paused by itself
    assert s.ask("pause") == ["^7from settings cfg paused the game"]
    assert s.ask("pause") == ["^7from settings cfg unpaused the game"]


def test_a_human_joining_unpauses_and_releases_the_queued_action(
    session: Callable[..., Session],
) -> None:
    s = session(
        settings_cfg=_TDM_ROTATION.replace("sv_autopause 0\n", ""),
        flags="autopause_delay=0.1,endmatch_delay=0.05,scoreboard_delay=0.05",
    )
    time.sleep(0.4)
    start = len(s.lines)
    s.send("endmatch")
    time.sleep(0.2)
    assert s.count(":gameover") == 0
    s.send("fake_join 1 1 127.0.0.1 Human")
    s.wait_for(":gamestart:tdm_boil:", after=start)
    # joining unpaused silently: no pause message was printed
    assert s.count("paused the game") == 0


def test_bots_do_not_unpause(session: Callable[..., Session]) -> None:
    s = session(
        settings_cfg=_TDM_ROTATION.replace("sv_autopause 0\n", ""),
        flags="autopause_delay=0.1,endmatch_delay=0.05",
    )
    time.sleep(0.4)
    s.send("fake_join 1 1 bot [BOT]x")
    s.send("endmatch")
    time.sleep(0.4)
    assert s.count(":gameover") == 0
