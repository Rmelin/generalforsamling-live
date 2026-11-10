"""API-tests af acceptkriterierne."""

from __future__ import annotations

import sqlite3
import threading

from fastapi.testclient import TestClient

from app.main import create_app

from .conftest import HEADERS, act, create, item_in_state, login, make_settings


def test_full_flow(foh, stage, anon):
    # 1. FOH opretter et punkt – det kan straks ses af alle
    item = create(foh, "Beretning", technical_notes="Trådløs håndholdt mikrofon.")
    assert item["status"] == "pending"
    assert item_in_state(anon, item["id"])["technical_notes"] == "Trådløs håndholdt mikrofon."

    # 2. Dirigenten vælger punktet
    r = act(stage, item["id"], "request", "pending")
    assert r.status_code == 200, r.text
    assert item_in_state(foh, item["id"])["status"] == "requested"

    # 3. FOH markerer klar
    assert act(foh, item["id"], "ready", "requested").status_code == 200
    assert item_in_state(stage, item["id"])["status"] == "ready"

    # 4. FOH starter
    r = act(foh, item["id"], "start", "ready")
    assert r.status_code == 200
    started = item_in_state(anon, item["id"])
    assert started["status"] == "live" and started["started_at"]

    # 5. FOH afslutter – punktet er ikke længere aktivt, men findes stadig
    assert act(foh, item["id"], "finish", "live").status_code == 200
    done = item_in_state(anon, item["id"])
    assert done["status"] == "done" and done["ended_at"]

    # 6. Kan genåbnes
    assert act(foh, item["id"], "reopen", "done").status_code == 200
    assert item_in_state(anon, item["id"])["status"] == "pending"


def test_stage_can_withdraw_until_live(foh, stage):
    item = create(foh)
    act(stage, item["id"], "request")
    act(foh, item["id"], "ready")
    assert act(stage, item["id"], "withdraw", "ready").status_code == 200
    assert item_in_state(foh, item["id"])["status"] == "pending"

    act(stage, item["id"], "request")
    act(foh, item["id"], "start")
    r = act(stage, item["id"], "withdraw", "live")
    assert r.status_code == 409
    assert item_in_state(foh, item["id"])["status"] == "live"


def test_stage_cannot_start_finish_or_edit(foh, stage):
    item = create(foh)
    for action in ("ready", "start", "finish", "cancel", "reopen"):
        assert act(stage, item["id"], action).status_code == 403, action
    assert stage.post("/api/items", json={"title": "x"}).status_code == 403
    assert stage.patch(f"/api/items/{item['id']}", json={"expected_version": 1, "title": "x"}).status_code == 403
    assert stage.delete(f"/api/items/{item['id']}").status_code == 403
    assert stage.get("/api/events").status_code == 403


def test_monitor_cannot_change_anything(foh, anon):
    item = create(foh)
    iid = item["id"]
    calls = [
        ("post", "/api/items", {"title": "x"}),
        ("patch", f"/api/items/{iid}", {"expected_version": 1, "title": "x"}),
        ("delete", f"/api/items/{iid}", None),
        ("post", f"/api/items/{iid}/move", {"direction": "up"}),
        ("get", "/api/events", None),
    ] + [("post", f"/api/items/{iid}/actions/{a}", {}) for a in
         ("request", "withdraw", "ready", "start", "finish", "cancel", "reopen")]
    for method, url, body in calls:
        kwargs = {"json": body} if body is not None else {}
        r = anon.request(method.upper(), url, **kwargs)
        assert r.status_code == 401, (method, url, r.status_code)
    assert item_in_state(anon, iid)["status"] == "pending"
    assert item_in_state(anon, iid)["title"] == "Punkt"
    # Monitoren kan læse
    assert anon.get("/monitor").status_code == 200
    assert anon.get("/api/state").status_code == 200


def test_pages_require_login(anon):
    assert anon.get("/foh", follow_redirects=False).status_code == 303
    assert anon.get("/stage", follow_redirects=False).status_code == 303
    assert anon.get("/monitor").status_code == 200


def test_stage_login_cannot_open_foh(stage):
    assert stage.get("/foh", follow_redirects=False).status_code == 303
    assert stage.get("/stage").status_code == 200


def test_wrong_password_rejected(anon):
    r = anon.post("/login", data={"mode": "foh", "username": "admin", "password": "forkert"},
                  follow_redirects=False)
    assert r.status_code == 401
    r = anon.post("/login", data={"mode": "stage", "password": "forkert"}, follow_redirects=False)
    assert r.status_code == 401


def test_write_requires_client_header(app, foh):
    with TestClient(app) as c:
        login(c, "foh")
        r = c.post("/api/items", json={"title": "x"})  # uden X-Live-Client
        assert r.status_code == 400


def test_passwords_stored_as_hashes(settings, app):
    con = sqlite3.connect(settings.database_path)
    rows = con.execute("select username, password_hash from users").fetchall()
    con.close()
    assert rows
    for _username, h in rows:
        assert h.startswith("pbkdf2_sha256$")
        assert settings.foh_password not in h and settings.stage_password not in h


def test_concurrent_status_changes_do_not_overwrite(foh, stage):
    """Dirigent trækker anmodning tilbage, mens FOH (med forældet visning) trykker Klar."""
    item = create(foh)
    act(stage, item["id"], "request", "pending")
    assert act(stage, item["id"], "withdraw", "requested").status_code == 200
    # FOH så stadig 'requested' – må ikke markere et punkt, dirigenten har fortrudt
    r = act(foh, item["id"], "ready", "requested")
    assert r.status_code == 409
    assert item_in_state(foh, item["id"])["status"] == "pending"


def test_stale_edit_rejected(foh):
    item = create(foh, "Original")
    r1 = foh.patch(f"/api/items/{item['id']}", json={"expected_version": 1, "title": "Første"})
    assert r1.status_code == 200 and r1.json()["item"]["version"] == 2
    r2 = foh.patch(f"/api/items/{item['id']}", json={"expected_version": 1, "title": "Gammel"})
    assert r2.status_code == 409
    assert item_in_state(foh, item["id"])["title"] == "Første"


def test_actions_are_idempotent(foh):
    item = create(foh)
    r1 = act(foh, item["id"], "start", "pending")
    r2 = act(foh, item["id"], "start", "pending")  # dobbeltklik
    assert r1.json()["changed"] is True
    assert r2.status_code == 200 and r2.json()["changed"] is False
    events = [e for e in foh.get("/api/events").json()["events"] if e["action"] == "start"]
    assert len(events) == 1


def test_parallel_requests_only_one_wins(app, foh):
    item = create(foh)
    results = []

    def worker():
        with TestClient(app) as c:
            c.headers.update(HEADERS)
            login(c, "foh")
            results.append(act(c, item["id"], "start", "pending").json().get("changed"))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1
    starts = [e for e in foh.get("/api/events").json()["events"] if e["action"] == "start"]
    assert len(starts) == 1


def test_starting_new_item_finishes_current(foh):
    a, b = create(foh, "A"), create(foh, "B")
    act(foh, a["id"], "start")
    act(foh, b["id"], "start")
    assert item_in_state(foh, a["id"])["status"] == "done"
    assert item_in_state(foh, b["id"])["status"] == "live"


def test_cancel_and_soft_delete_keep_data(foh, settings):
    a, b = create(foh, "A"), create(foh, "B")
    assert act(foh, a["id"], "cancel").status_code == 200
    assert foh.delete(f"/api/items/{b['id']}").status_code == 200
    assert item_in_state(foh, a["id"])["status"] == "cancelled"
    assert item_in_state(foh, b["id"]) is None  # skjult
    con = sqlite3.connect(settings.database_path)
    assert con.execute("select count(*) from items").fetchone()[0] == 2  # intet slettet permanent
    con.close()


def test_move_changes_order(foh):
    a, b, c = create(foh, "A"), create(foh, "B"), create(foh, "C")
    foh.post(f"/api/items/{c['id']}/move", json={"direction": "up"})
    order = [i["title"] for i in foh.get("/api/state").json()["items"]]
    assert order == ["A", "C", "B"]
    r = foh.post(f"/api/items/{a['id']}/move", json={"direction": "up"})
    assert r.json()["changed"] is False


def test_event_log_records_transitions(foh, stage):
    item = create(foh)
    act(stage, item["id"], "request")
    act(foh, item["id"], "ready")
    events = foh.get("/api/events").json()["events"]
    ready = next(e for e in events if e["action"] == "ready")
    assert ready["from_status"] == "requested" and ready["to_status"] == "ready"
    assert ready["actor"] == "foh:admin" and ready["item_id"] == item["id"]
    req = next(e for e in events if e["action"] == "request")
    assert req["actor"] == "stage:scene"


def test_validation(foh):
    assert foh.post("/api/items", json={"title": ""}).status_code == 422
    assert foh.post("/api/items", json={"title": "x", "item_type": "dans"}).status_code == 422
    assert foh.post("/api/items", json={"title": "x", "duration_seconds": -1}).status_code == 422
    assert act(foh, 99999, "start").status_code == 404


def test_restart_keeps_items_and_history(tmp_path):
    settings = make_settings(tmp_path)
    app1 = create_app(settings)
    with TestClient(app1) as c:
        c.headers.update(HEADERS)
        login(c, "foh")
        item = create(c, "Overlever genstart")
        act(c, item["id"], "start")
        rev_before = c.get("/api/state").json()["revision"]

    app2 = create_app(make_settings(tmp_path))  # ny proces, samme database
    with TestClient(app2) as c:
        c.headers.update(HEADERS)
        login(c, "foh")
        state = c.get("/api/state").json()
        assert state["revision"] == rev_before
        it = next(i for i in state["items"] if i["id"] == item["id"])
        assert it["status"] == "live" and it["title"] == "Overlever genstart"
        actions = [e["action"] for e in c.get("/api/events").json()["events"]]
        assert "create" in actions and "start" in actions


def test_optional_flag_create_and_update(foh, anon):
    must = create(foh, "Skal afvikles")
    maybe = create(foh, "Mulighed", optional=True)
    assert must["optional"] is False and maybe["optional"] is True
    r = foh.patch(f"/api/items/{must['id']}", json={"expected_version": 1, "optional": True})
    assert r.status_code == 200 and r.json()["item"]["optional"] is True
    assert item_in_state(anon, must["id"])["optional"] is True
    edit = next(e for e in foh.get("/api/events").json()["events"] if e["action"] == "edit")
    assert edit["details"] == "optional"


def test_old_database_is_migrated(tmp_path):
    """En database fra før 'optional'-feltet får kolonnen tilføjet ved opstart."""
    db_path = tmp_path / "live.db"
    con = sqlite3.connect(db_path)
    con.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, title VARCHAR(200), item_type VARCHAR(20), "
        "description TEXT, technical_notes TEXT, duration_seconds INTEGER, status VARCHAR(20), "
        "sort_order INTEGER, version INTEGER, deleted BOOLEAN, created_at DATETIME, updated_at DATETIME, "
        "requested_at DATETIME, ready_at DATETIME, started_at DATETIME, ended_at DATETIME)"
    )
    con.execute(
        "INSERT INTO items (title, item_type, description, technical_notes, duration_seconds, status, "
        "sort_order, version, deleted, created_at, updated_at) VALUES "
        "('Gammelt punkt', 'speech', '', '', 60, 'pending', 10, 1, 0, '2026-01-01', '2026-01-01')"
    )
    con.commit()
    con.close()

    app = create_app(make_settings(tmp_path))
    with TestClient(app) as c:
        items = c.get("/api/state").json()["items"]
        assert items[0]["title"] == "Gammelt punkt" and items[0]["optional"] is False
