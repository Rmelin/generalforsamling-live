"""Tilsluttede skærme: FOH kan se, om scenen (og Presto) er tilsluttet."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.realtime import Connection, ConnectionManager

from .conftest import HEADERS, create, make_settings

TOKEN = "presto-test-token-1234567890"


def _next(ws, kind, max_msgs=10, until=None):
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg["type"] == kind and (until is None or until(msg)):
            return msg
    raise AssertionError(f"{kind} modtaget ikke")


def _skip_welcome(ws):
    msg = ws.receive_json()
    while msg["type"] == "welcome":
        msg = ws.receive_json()
    return msg


def _hello(ws, page, **extra):
    ws.send_json({"type": "hello", "page": page, "screen": "800x480", **extra})


def test_foh_sees_stage_connect_and_disconnect(foh, stage):
    with foh.websocket_connect("/ws") as foh_ws:
        _hello(foh_ws, "foh")
        welcome = _next(foh_ws, "welcome")
        assert welcome["kind"] == "foh"
        p = _next(foh_ws, "presence")
        assert p["stages"] == 0
        assert p["clients"][0]["id"] == welcome["id"]
        assert [c["kind"] for c in p["clients"]] == ["foh"]
        assert p["clients"][0]["name"] == ""

        with stage.websocket_connect("/ws") as stage_ws:
            _hello(stage_ws, "stage", name="Talerstol")
            p = _next(foh_ws, "presence", until=lambda m: m["stages"] == 1)
            st = next(c for c in p["clients"] if c["kind"] == "stage")
            assert st["name"] == "Talerstol"
            assert st["screen"] == "800x480"
            assert st["visible"] is True

            stage_ws.send_json({"type": "visibility", "visible": False})
            p = _next(foh_ws, "presence", until=lambda m: any(
                c["kind"] == "stage" and not c["visible"] for c in m["clients"]))

        # Scenen lukker – FOH får besked med det samme
        _next(foh_ws, "presence", until=lambda m: m["stages"] == 0)


def test_anonymous_cannot_pose_as_stage_or_foh(foh, anon):
    with foh.websocket_connect("/ws") as foh_ws:
        _hello(foh_ws, "foh")
        _next(foh_ws, "presence")
        with anon.websocket_connect("/ws") as ws:
            _hello(ws, "stage")
            p = _next(foh_ws, "presence", until=lambda m: len(m["clients"]) == 2)
            assert p["stages"] == 0
            assert sorted(c["kind"] for c in p["clients"]) == ["foh", "monitor"]


def test_stage_login_cannot_pose_as_foh(foh, stage):
    with foh.websocket_connect("/ws") as foh_ws:
        _hello(foh_ws, "foh")
        _next(foh_ws, "presence")
        with stage.websocket_connect("/ws") as ws:
            _hello(ws, "foh")
            p = _next(foh_ws, "presence", until=lambda m: len(m["clients"]) == 2)
            assert sorted(c["kind"] for c in p["clients"]) == ["foh", "monitor"]


def test_presence_is_only_sent_to_foh(foh, stage, anon):
    with stage.websocket_connect("/ws") as stage_ws, anon.websocket_connect("/ws") as mon_ws:
        _hello(stage_ws, "stage")
        _hello(mon_ws, "monitor")
        assert _skip_welcome(stage_ws)["type"] == "snapshot"
        assert _skip_welcome(mon_ws)["type"] == "snapshot"
        with foh.websocket_connect("/ws") as foh_ws:
            _hello(foh_ws, "foh")
            _next(foh_ws, "presence", until=lambda m: len(m["clients"]) == 3)
            create(foh, "Udløser et snapshot")
            # Det næste, scene og monitor modtager, er snapshot – ikke presence med IP-adresser.
            assert _skip_welcome(stage_ws)["type"] == "snapshot"
            assert _skip_welcome(mon_ws)["type"] == "snapshot"


def test_presence_endpoint_is_foh_only(foh, stage, anon):
    assert foh.get("/api/presence").status_code == 200
    assert stage.get("/api/presence").status_code in (401, 403)
    assert anon.get("/api/presence").status_code in (401, 403)


def test_presto_shows_up_when_it_polls(tmp_path):
    settings = make_settings(tmp_path)
    settings.device_token = TOKEN
    app = create_app(settings)
    with TestClient(app) as c:
        c.headers.update(HEADERS)
        from .conftest import login
        login(c, "foh")
        assert c.get("/api/presence").json()["devices"] == []
        with TestClient(app) as dev:
            r = dev.get("/api/device/state", headers={"Authorization": f"Bearer {TOKEN}"})
            assert r.status_code == 200
        devices = c.get("/api/presence").json()["devices"]
        assert [d["name"] for d in devices] == ["Presto"]
        assert devices[0]["online"] is True
        # FOH's eget kald til samme endpoint tæller ikke som en Presto
        c.get("/api/device/state")
        assert len(c.get("/api/presence").json()["devices"]) == 1


class _FakeWS:
    async def send_text(self, _text):
        pass


def test_silent_clients_are_dropped_but_old_clients_are_not():
    async def run():
        m = ConnectionManager()
        greeted, legacy = Connection(_FakeWS()), Connection(_FakeWS())
        m.add(greeted)
        m.add(legacy)
        m.hello(greeted, {"page": "stage"}, {"monitor", "stage"})
        now = greeted.last_seen
        assert m.sweep(25, now=now + 10) == []
        dropped = m.sweep(25, now=now + 30)
        # Kun klienten, der har sagt hello (og dermed svarer på ping), afbrydes.
        assert dropped == [greeted]
        assert m.connections == {legacy}
        assert await asyncio.wait_for(greeted.queue.get(), 1) is None
        assert m.presence()["stages"] == 0

    asyncio.run(run())


@pytest.mark.parametrize("name,expected", [("  Talerstol  ", "Talerstol"), ("x" * 100, "x" * 40),
                                           ("a\nb", "ab"), (None, "")])
def test_screen_names_are_cleaned(name, expected):
    async def run():
        m = ConnectionManager()
        c = Connection(_FakeWS())
        m.hello(c, {"page": "monitor", "name": name}, {"monitor"})
        return c.name

    assert asyncio.run(run()) == expected
