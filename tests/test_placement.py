"""Placering af punkter (træk og slip / indsæt efter) og fortryd afslutning."""

from __future__ import annotations

from .conftest import act, create, item_in_state


def _order(client):
    return [i["title"] for i in client.get("/api/state").json()["items"]
            if i["status"] in ("pending", "requested", "ready", "live")]


def _place(client, item_id, **body):
    return client.post(f"/api/items/{item_id}/place", json=body)


def test_place_before_and_after(foh):
    a, b, c, d = (create(foh, t) for t in "ABCD")
    assert _place(foh, d["id"], before_id=b["id"]).json()["changed"] is True
    assert _order(foh) == ["A", "D", "B", "C"]
    assert _place(foh, a["id"], after_id=c["id"]).status_code == 200
    assert _order(foh) == ["D", "B", "C", "A"]
    # Uændret placering er en no-op
    assert _place(foh, a["id"], after_id=c["id"]).json()["changed"] is False


def test_place_top_bottom_after_live(foh):
    a, b, c, d = (create(foh, t) for t in "ABCD")
    act(foh, b["id"], "start")
    _place(foh, d["id"], where="after_live")
    assert _order(foh) == ["A", "B", "D", "C"]
    _place(foh, c["id"], where="top")
    assert _order(foh) == ["C", "A", "B", "D"]
    _place(foh, c["id"], where="bottom")
    assert _order(foh) == ["A", "B", "D", "C"]
    assert a["id"]


def test_place_target_gone_is_conflict(foh):
    a, b = create(foh, "A"), create(foh, "B")
    act(foh, b["id"], "cancel")
    r = _place(foh, a["id"], before_id=b["id"])
    assert r.status_code == 409
    assert _place(foh, b["id"], where="top").status_code == 409  # annulleret punkt kan ikke flyttes


def test_move_is_logged_and_broadcast(foh, anon):
    a, b = create(foh, "A"), create(foh, "B")
    with anon.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        _place(foh, b["id"], before_id=a["id"])
        snap = ws.receive_json()
        assert snap["revision"] > first["revision"]
        assert [i["title"] for i in snap["items"]][:2] == ["B", "A"]
    ev = next(e for e in foh.get("/api/events").json()["events"] if e["action"] == "move")
    assert ev["details"] == "før 'A'"


def test_create_after_item_and_after_live(foh):
    a, b, c = create(foh, "A"), create(foh, "B"), create(foh, "C")
    r = foh.post("/api/items", json={"title": "Ny", "after_id": a["id"]})
    assert r.status_code == 201
    assert _order(foh) == ["A", "Ny", "B", "C"]
    act(foh, b["id"], "start")
    foh.post("/api/items", json={"title": "Efter live", "place": "after_live"})
    assert _order(foh) == ["A", "Ny", "B", "Efter live", "C"]
    foh.post("/api/items", json={"title": "Sidst"})
    assert _order(foh)[-1] == "Sidst"
    assert c["id"]


def test_create_after_missing_item_creates_nothing(foh):
    a = create(foh, "A")
    act(foh, a["id"], "cancel")
    r = foh.post("/api/items", json={"title": "Ny", "after_id": a["id"]})
    assert r.status_code == 409
    assert all(i["title"] != "Ny" for i in foh.get("/api/state").json()["items"])


def test_stage_cannot_place(foh, stage):
    a = create(foh, "A")
    assert _place(stage, a["id"], where="top").status_code == 403


def test_unfinish_restores_live_with_original_start(foh):
    a = create(foh, "A")
    act(foh, a["id"], "start")
    started = item_in_state(foh, a["id"])["started_at"]
    act(foh, a["id"], "finish", "live")
    r = act(foh, a["id"], "unfinish", "done")
    assert r.status_code == 200
    it = item_in_state(foh, a["id"])
    assert it["status"] == "live" and it["started_at"] == started and it["ended_at"] is None


def test_unfinish_blocked_when_other_item_live(foh):
    a, b = create(foh, "A"), create(foh, "B")
    act(foh, a["id"], "start")
    act(foh, a["id"], "finish")
    act(foh, b["id"], "start")
    r = act(foh, a["id"], "unfinish", "done")
    assert r.status_code == 409
    assert item_in_state(foh, a["id"])["status"] == "done"


def test_only_foh_can_unfinish(foh, stage):
    a = create(foh, "A")
    act(foh, a["id"], "start")
    act(foh, a["id"], "finish")
    assert act(stage, a["id"], "unfinish").status_code == 403
