"""Kører Presto-programmets logik (presto/main.py) mod serveren uden hardware."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

from .conftest import HEADERS, act, create, item_in_state, login, make_settings

TOKEN = "presto-test-token-1234567890"
MAIN = Path(__file__).resolve().parent.parent / "presto" / "main.py"


class _Resp:
    def __init__(self, r):
        self.status_code = r.status_code
        self._r = r

    def json(self):
        return self._r.json()

    def close(self):
        pass


def _load_presto(client: TestClient, online: dict):
    """Importér presto/main.py med falske 'config'- og 'requests'-moduler."""

    def request(method, url, data=None, headers=None, timeout=None):
        if not online["up"]:
            raise OSError("ECONNREFUSED")
        path = url.split("://", 1)[1].split("/", 1)[1]
        r = client.request(method, "/" + path, content=data, headers=headers)
        return _Resp(r)

    fake_requests = types.SimpleNamespace(request=request)
    fake_config = types.SimpleNamespace(
        SERVER="http://server:8000", DEVICE_TOKEN=TOKEN, POLL_MS=1000, USE_LEDS=False, BUZZER_PIN=None
    )
    saved = {k: sys.modules.get(k) for k in ("config", "urequests", "requests")}
    sys.modules["config"] = fake_config
    sys.modules["urequests"] = fake_requests
    try:
        spec = importlib.util.spec_from_file_location("presto_main", MAIN)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return mod


@pytest.fixture
def env(tmp_path):
    settings = make_settings(tmp_path)
    settings.device_token = TOKEN
    app = create_app(settings)
    with TestClient(app) as foh, TestClient(app) as stage, TestClient(app) as dev:
        for c in (foh, stage, dev):
            c.headers.update(HEADERS)
        login(foh, "foh")
        login(stage, "stage")
        online = {"up": True}
        mod = _load_presto(dev, online)
        yield mod, foh, stage, online


def _tap(app, key):
    app.draw()
    for (x, y, w, h, k, _a, _i) in app.buttons:
        if k == key:
            return app.press(k, _a, _i)
    raise AssertionError(f"knap {key} findes ikke: {[b[4] for b in app.buttons]}")


def _keys(app):
    app.draw()
    return [b[4] for b in app.buttons]


def test_full_flow_from_presto(env):
    mod, foh, stage, _ = env
    video = create(foh, "Film om året", item_type="video", duration_seconds=90)
    talk = create(foh, "Beretning")
    app = mod.App()

    assert app.poll() and app.online
    assert app.state["next"]["id"] == video["id"] and not app.state["next_chosen"]

    act(stage, talk["id"], "request", "pending")  # dirigenten ønsker talen
    app.poll()
    assert app.state["next"]["id"] == talk["id"] and app.state["requests"] == 1
    assert _keys(app) == ["ready", "start", "cancel"]

    assert _tap(app, "ready") == "ok"
    assert item_in_state(foh, talk["id"])["status"] == "ready"
    assert _keys(app) == ["start", "cancel"]  # KLAR forsvinder, når punktet er klar

    assert _tap(app, "start") == "ok"
    assert item_in_state(foh, talk["id"])["status"] == "live"
    assert "finish" in _keys(app)
    assert app.remaining_now(app.state["current"]) is None  # tale: ingen nedtælling

    # START mens noget afvikles kræver bekræftelse
    assert _tap(app, "start") == "confirm"
    assert item_in_state(foh, video["id"])["status"] == "pending"
    assert _tap(app, "start") == "ok"
    assert item_in_state(foh, video["id"])["status"] == "live"
    assert 0 < app.remaining_now(app.state["current"]) <= 90  # video tæller ned

    assert _tap(app, "finish") == "ok"
    assert item_in_state(foh, video["id"])["status"] == "done"
    events = {e["actor"] for e in foh.get("/api/events").json()["events"] if e["action"] in ("ready", "start", "finish")}
    assert events == {"device:presto"}


def test_cancel_needs_two_taps(env):
    mod, foh, _stage, _ = env
    item = create(foh, "Måske")
    app = mod.App()
    app.poll()
    assert _tap(app, "cancel") == "confirm"
    assert item_in_state(foh, item["id"])["status"] == "pending"
    assert _tap(app, "cancel") == "ok"
    assert item_in_state(foh, item["id"])["status"] == "cancelled"


def test_stale_state_gives_conflict_not_overwrite(env):
    mod, foh, stage, _ = env
    item = create(foh, "Punkt")
    act(stage, item["id"], "request", "pending")
    app = mod.App()
    app.poll()
    act(stage, item["id"], "withdraw", "requested")  # dirigenten fortryder
    assert _tap(app, "ready") == "conflict"  # Presto så stadig 'requested'
    assert item_in_state(foh, item["id"])["status"] == "pending"


def test_offline_is_detected_and_recovers(env):
    mod, foh, _stage, online = env
    item = create(foh, "Punkt")
    app = mod.App()
    app.poll()
    online["up"] = False
    assert app.poll() is False and app.online is False
    assert _tap(app, "start") == "error"
    assert item_in_state(foh, item["id"])["status"] == "pending"
    online["up"] = True
    assert app.poll() and app.online


def test_text_helpers(env):
    mod = env[0]
    assert mod.ascii_text("Æblegrød – på Øen") == "Aeblegroed - paa Oeen"
    assert mod.fmt_dur(95) == "1:35" and mod.fmt_dur(-5) == "+0:05"
    assert mod.fmt_approx(300) == "ca. 5 min"


def test_offline_shows_reason(env):
    mod, _foh, _stage, online = env
    app = mod.App()
    online["up"] = False
    app.poll()
    assert app.online is False and "ECONNREFUSED" in app.error or app.error
    # Kendte fejlkoder oversættes
    assert "Afvist" in mod.explain_error(OSError(111))
    assert "Timeout" in mod.explain_error(OSError(110))
    assert "slaa serveradressen op" in mod.explain_error(OSError(-2))


def test_wrong_token_is_explained(env):
    mod = env[0]
    app = mod.App()
    app.server.headers["Authorization"] = "Bearer forkert"
    assert app.poll() is False
    assert "401" in app.error and "DEVICE_TOKEN" in app.error
