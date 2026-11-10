"""Fysisk FOH-betjening (Pimoroni Presto) via enhedsnøgle."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

from .conftest import HEADERS, act, create, item_in_state, login, make_settings

TOKEN = "presto-test-token-1234567890"


@pytest.fixture
def device_app(tmp_path):
    settings = make_settings(tmp_path)
    settings.device_token = TOKEN
    return create_app(settings)


@pytest.fixture
def fohc(device_app):
    with TestClient(device_app) as c:
        c.headers.update(HEADERS)
        yield login(c, "foh")


@pytest.fixture
def device(device_app):
    with TestClient(device_app) as c:
        c.headers.update({**HEADERS, "Authorization": f"Bearer {TOKEN}"})
        yield c


def test_device_state_is_compact(fohc, device):
    a = create(fohc, "Velkomst")
    b = create(fohc, "Film", item_type="video", duration_seconds=90)
    r = device.get("/api/device/state")
    assert r.status_code == 200
    s = r.json()
    assert s["current"] is None
    assert s["next"]["id"] == a["id"] and s["next_chosen"] is False  # næste i programmet
    assert s["remaining"] == 2

    act(fohc, b["id"], "request")
    s = device.get("/api/device/state").json()
    assert s["next"]["id"] == b["id"] and s["next_chosen"] is True and s["requests"] == 1

    act(fohc, b["id"], "start")
    s = device.get("/api/device/state").json()
    assert s["current"]["id"] == b["id"]
    assert s["current"]["timed"] is True
    assert 0 < s["current"]["remaining_seconds"] <= 90


def test_speech_has_no_countdown(fohc, device):
    a = create(fohc, "Tale")
    act(fohc, a["id"], "start")
    cur = device.get("/api/device/state").json()["current"]
    assert cur["timed"] is False and "remaining_seconds" not in cur


def test_device_can_ready_start_finish_cancel(fohc, device):
    a, b = create(fohc, "A"), create(fohc, "B")
    assert act(device, a["id"], "ready", "pending").status_code == 200
    assert act(device, a["id"], "start", "ready").status_code == 200
    assert act(device, a["id"], "finish", "live").status_code == 200
    assert act(device, b["id"], "cancel", "pending").status_code == 200
    assert item_in_state(fohc, a["id"])["status"] == "done"
    assert item_in_state(fohc, b["id"])["status"] == "cancelled"
    actors = {e["actor"] for e in fohc.get("/api/events").json()["events"] if e["action"] != "create"}
    assert actors == {"device:presto"}


def test_device_cannot_edit_or_do_stage_actions(fohc, device):
    a = create(fohc, "A")
    assert device.post("/api/items", json={"title": "x"}).status_code == 401
    assert device.patch(f"/api/items/{a['id']}", json={"expected_version": 1, "title": "x"}).status_code == 401
    assert device.delete(f"/api/items/{a['id']}").status_code == 401
    assert device.get("/api/events").status_code == 401
    assert act(device, a["id"], "request").status_code == 403
    assert act(device, a["id"], "reopen").status_code == 403


def test_wrong_or_missing_token_rejected(device_app):
    with TestClient(device_app) as c:
        c.headers.update(HEADERS)
        assert c.get("/api/device/state").status_code == 401
        c.headers["Authorization"] = "Bearer forkert"
        assert c.get("/api/device/state").status_code == 401


def test_device_disabled_without_token(foh, anon):
    a = create(foh, "A")
    anon.headers["Authorization"] = "Bearer "
    assert anon.get("/api/device/state").status_code == 401
    assert act(anon, a["id"], "start").status_code == 401
