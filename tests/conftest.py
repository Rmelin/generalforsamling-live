from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

FOH_USER, FOH_PASS, STAGE_PASS = "admin", "foh-test-pw", "scene-test-pw"
HEADERS = {"X-Live-Client": "1"}


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "live.db",
        secret_key="test-secret",
        foh_username=FOH_USER,
        foh_password=FOH_PASS,
        stage_password=STAGE_PASS,
        seed_demo_data=False,
        ping_interval=3600,
    )


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture
def app(settings):
    return create_app(settings)


def _client(app) -> TestClient:
    c = TestClient(app)
    c.headers.update(HEADERS)
    return c


def login(client: TestClient, mode: str) -> TestClient:
    if mode == "foh":
        data = {"mode": "foh", "username": FOH_USER, "password": FOH_PASS, "next": "/foh"}
    else:
        data = {"mode": "stage", "password": STAGE_PASS, "next": "/stage"}
    r = client.post("/login", data=data, follow_redirects=False)
    assert r.status_code == 303, r.text
    return client


@pytest.fixture
def foh(app):
    with _client(app) as c:
        yield login(c, "foh")


@pytest.fixture
def stage(app):
    with _client(app) as c:
        yield login(c, "stage")


@pytest.fixture
def anon(app):
    with _client(app) as c:
        yield c


def create(foh: TestClient, title="Punkt", **kw) -> dict:
    payload = {"title": title, "item_type": "speech", "duration_seconds": 120, **kw}
    r = foh.post("/api/items", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["item"]


def act(client: TestClient, item_id: int, action: str, expected_status=None):
    body = {} if expected_status is None else {"expected_status": expected_status}
    return client.post(f"/api/items/{item_id}/actions/{action}", json=body)


def item_in_state(client: TestClient, item_id: int) -> dict | None:
    for it in client.get("/api/state").json()["items"]:
        if it["id"] == item_id:
            return it
    return None
