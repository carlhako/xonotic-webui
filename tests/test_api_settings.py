"""Server-settings HTTP API against a live panel and the fake dedicated server."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from tests.conftest import Live

LiveFactory = Callable[..., "asyncio.Future[Live]"]


def _by_key(body: dict) -> dict[str, dict]:
    return {s["key"]: s for s in body["settings"]}


async def _console_lines(client: httpx.AsyncClient, n: int = 0) -> list[dict]:
    """The retained console history, via the stream (stops when it goes quiet)."""
    lines: list[dict] = []
    try:
        async with asyncio.timeout(0.6):
            async with client.stream("GET", "/api/console/stream") as response:
                async for raw in response.aiter_lines():
                    if raw.startswith("data: "):
                        lines.append(json.loads(raw[6:]))
    except TimeoutError:
        pass
    return lines


async def test_settings_while_stopped_show_defaults_and_no_live_values(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        body = (await client.get("/api/settings")).json()
        assert body["running"] is False
        assert [g["id"] for g in body["groups"]] == [
            "identity",
            "match",
            "bots",
            "voting",
            "mutators",
            "server",
        ]
        settings = _by_key(body)
        assert settings["hostname"]["value"] is None
        assert settings["hostname"]["default"] == "Xonotic 0.8.6 Server"
        assert settings["hostname"]["live_value"] is None
        assert settings["sv_autopause"]["default"] is True  # enabled unless changed
        assert settings["timelimit_override"]["value_labels"][0] == {
            "value": -1,
            "label": "Map default",
        }
        assert all(s["server_cfg"] is False for s in settings.values())
        assert settings["g_maplist_votable"]["switch"] == {
            "label": "Voting enabled",
            "help": settings["g_maplist_votable"]["switch"]["help"],
            "off_value": 0,
            "enables": ["g_maplist_votable_timeout"],
        }
        assert settings["hostname"]["switch"] is None


async def test_patch_while_stopped_saves_and_reports_next_start(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        r = await client.patch("/api/settings", json={"hostname": "LAN Party", "skill": 5})
        assert r.status_code == 200
        assert r.json() == {"applied": {"hostname": "next_start", "skill": "next_start"}}
        settings = _by_key((await client.get("/api/settings")).json())
        assert settings["hostname"]["value"] == "LAN Party"
        assert settings["skill"]["value"] == 5
        assert (await client.post("/api/lifecycle/start")).status_code == 200
        body = (await client.get("/api/settings")).json()
        assert _by_key(body)["hostname"]["live_value"] == "LAN Party"
        await client.post("/api/lifecycle/stop")


async def test_patch_while_running_reports_each_class_and_shows_live_values(
    live: LiveFactory,
) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        await client.post("/api/lifecycle/start")
        r = await client.patch(
            "/api/settings",
            json={"hostname": "x", "g_instagib": True, "maxplayers": 8, "timelimit_override": 10},
        )
        assert r.json()["applied"] == {
            "hostname": "now",
            "g_instagib": "next_map",
            "maxplayers": "next_start",
            "timelimit_override": "now",
        }
        body = (await client.get("/api/settings")).json()
        assert body["running"] is True
        settings = _by_key(body)
        assert settings["hostname"]["live_value"] == "x"
        assert settings["timelimit_override"]["live_value"] == "10"  # the match's time limit
        assert settings["bot_number"]["live_value"] == "0"
        # the live change is in the console history, as an operator command
        lines = await _console_lines(client)
        assert any(line["kind"] == "command" and line["plain"] == 'hostname "x"' for line in lines)
        await client.post("/api/lifecycle/stop")


async def test_patch_null_resets_to_the_default(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        await client.patch("/api/settings", json={"skill": 3})
        r = await client.patch("/api/settings", json={"skill": None})
        assert r.status_code == 200
        assert _by_key((await client.get("/api/settings")).json())["skill"]["value"] is None


@pytest.mark.parametrize(
    ("body", "code", "field", "text"),
    [
        ({"skill": 99}, "invalid_setting", "skill", "between 0 and 10"),
        ({"sv_motd": 'say "hi"'}, "invalid_setting", "sv_motd", "double quote"),
        ({"sv_motd": "a\nb"}, "invalid_setting", "sv_motd", "line break"),
        ({"sv_motd": "a\\b"}, "invalid_setting", "sv_motd", "backslash"),
        ({"nope": 1}, "unknown_setting", "nope", "unknown setting"),
        ({"skill": "high"}, "invalid_setting", "skill", "number"),
        ({"g_instagib": 1}, "invalid_setting", "g_instagib", "on or off"),
    ],
)
async def test_rejections_use_stable_codes_and_save_nothing(
    live: LiveFactory, body: dict, code: str, field: str | None, text: str
) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.patch("/api/settings", json={"hostname": "kept?", **body})
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["code"] == code
        assert detail.get("field") == field
        assert text in detail["message"]
        # all or nothing: the valid hostname in the same request was not saved either
        assert _by_key((await client.get("/api/settings")).json())["hostname"]["value"] is None


async def test_an_empty_patch_is_rejected(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.patch("/api/settings", json={})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "invalid_setting"


async def test_injection_shaped_input_is_delivered_literally(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        await client.post("/api/lifecycle/start")
        r = await client.patch(
            "/api/settings", json={"sv_motd": "Welcome; have fun", "hostname": "$hostname rocks"}
        )
        assert r.status_code == 200
        settings = _by_key((await client.get("/api/settings")).json())
        assert settings["sv_motd"]["live_value"] == "Welcome; have fun"
        assert settings["hostname"]["live_value"] == "$hostname rocks"
        lines = await _console_lines(client)
        assert not any('Unknown command "have' in line["plain"] for line in lines)
        await client.post("/api/lifecycle/stop")


async def test_server_cfg_overlap_is_flagged(live: LiveFactory) -> None:
    app = await live()
    server_cfg = app.settings.userdir / "data" / "server.cfg"
    server_cfg.parent.mkdir(parents=True)
    server_cfg.write_text('hostname "Old Name"\n')
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        settings = _by_key((await client.get("/api/settings")).json())
        assert settings["hostname"]["server_cfg"] is True
        assert settings["skill"]["server_cfg"] is False


# --- raw overrides and the catalogue -------------------------------------------------


async def test_overrides_add_change_and_remove(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        r = await client.put(
            "/api/settings/overrides/g_balance_health_start", json={"value": "150"}
        )
        assert r.status_code == 200
        assert r.json() == {"name": "g_balance_health_start", "apply": "next_start"}  # stopped
        r = await client.put(
            "/api/settings/overrides/g_balance_health_start", json={"value": "175"}
        )
        listed = (await client.get("/api/settings/overrides")).json()
        assert listed["overrides"] == [
            {
                "name": "g_balance_health_start",
                "value": "175",
                "live_value": None,
                "server_cfg": False,
            }
        ]
        r = await client.delete("/api/settings/overrides/g_balance_health_start")
        assert r.status_code == 200
        assert (await client.get("/api/settings/overrides")).json()["overrides"] == []


async def test_override_while_running_is_sent_and_may_need_a_restart(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        await client.post("/api/lifecycle/start")
        r = await client.put("/api/settings/overrides/my_mod_option", json={"value": "on"})
        assert r.json()["apply"] == "may_need_restart"
        listed = (await client.get("/api/settings/overrides")).json()
        assert listed["running"] is True
        assert listed["overrides"][0]["live_value"] == "on"
        await client.post("/api/lifecycle/stop")


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("sv_eventlog", "reserved_cvar"),
        ("g_playerstats_gamereport_uri", "reserved_cvar"),
        ("port", "reserved_cvar"),
        ("rcon_password", "reserved_cvar"),
        ("has%20space", "invalid_cvar_name"),
        ("semi%3Bcolon", "invalid_cvar_name"),
    ],
)
async def test_invalid_and_reserved_overrides_are_rejected(
    live: LiveFactory, name: str, code: str
) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.put(f"/api/settings/overrides/{name}", json={"value": "0"})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == code
        assert (await client.get("/api/settings/overrides")).json()["overrides"] == []
        assert not app.settings.game_settings_file.exists()


async def test_cvar_search_while_stopped_and_running(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url, timeout=30) as client:
        page = (await client.get("/api/cvars", params={"q": "maplist", "limit": 10})).json()
        assert page["running"] is False
        assert page["total"] >= 21 and len(page["items"]) == 10
        assert all(i["live_value"] is None for i in page["items"])
        assert page["items"][0]["description"]

        await client.post("/api/lifecycle/start")
        await client.put("/api/settings/overrides/g_maplist_votable", json={"value": "3"})
        page = (await client.get("/api/cvars", params={"q": "g_maplist_votable"})).json()
        by_name = {i["name"]: i for i in page["items"]}
        assert by_name["g_maplist_votable"]["live_value"] == "3"
        assert by_name["g_maplist_votable"]["override"] == "3"
        assert by_name["g_maplist_votable_timeout"]["live_value"] == "30"
        await client.post("/api/lifecycle/stop")


async def test_reserved_cvars_are_listed_read_only(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        page = (await client.get("/api/cvars", params={"q": "sv_eventlog"})).json()
        by_name = {i["name"]: i for i in page["items"]}
        assert by_name["sv_eventlog"]["editable"] is False
        assert (await client.get("/api/cvars", params={"q": "hostname"})).json()["items"][0][
            "editable"
        ]


async def test_cvar_search_paging_and_bounds(live: LiveFactory) -> None:
    app = await live()
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.get("/api/cvars", params={"limit": 500})
        assert r.status_code == 422
        a = (await client.get("/api/cvars", params={"q": "g_maplist", "limit": 5})).json()
        b = (
            await client.get("/api/cvars", params={"q": "g_maplist", "limit": 5, "offset": 5})
        ).json()
        assert a["total"] == b["total"]
        assert not {i["name"] for i in a["items"]} & {i["name"] for i in b["items"]}


async def test_an_unreadable_settings_file_is_a_clear_error_and_is_kept(
    live: LiveFactory,
) -> None:
    app = await live()
    app.settings.game_settings_file.parent.mkdir(parents=True, exist_ok=True)
    app.settings.game_settings_file.write_text("{oops")
    async with httpx.AsyncClient(base_url=app.base_url) as client:
        r = await client.get("/api/settings")
        assert r.status_code == 500
        assert r.json()["detail"]["code"] == "settings_unreadable"
        r = await client.patch("/api/settings", json={"skill": 3})
        assert r.status_code == 500
        assert app.settings.game_settings_file.read_text() == "{oops"
