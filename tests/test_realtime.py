"""WebSocket-synkronisering."""

from __future__ import annotations

from .conftest import act, create


def _next_snapshot(ws):
    while True:
        msg = ws.receive_json()
        if msg["type"] == "snapshot":
            return msg


def _wait_for_status(ws, item_id, status, max_msgs=10):
    for _ in range(max_msgs):
        snap = _next_snapshot(ws)
        it = next((i for i in snap["items"] if i["id"] == item_id), None)
        if it and it["status"] == status:
            return snap
    raise AssertionError(f"status {status} modtaget ikke")


def test_new_client_gets_current_state(foh, anon):
    item = create(foh, "Midt i afviklingen")
    act(foh, item["id"], "start")
    # En ny browser, der åbnes midt under afviklingen
    with anon.websocket_connect("/ws") as ws:
        snap = _next_snapshot(ws)
        live = [i for i in snap["items"] if i["status"] == "live"]
        assert [i["title"] for i in live] == ["Midt i afviklingen"]


def test_changes_are_pushed_to_all_clients(foh, stage, anon):
    with anon.websocket_connect("/ws") as monitor_ws, stage.websocket_connect("/ws") as stage_ws, \
            foh.websocket_connect("/ws") as foh_ws:
        initial = [_next_snapshot(w)["revision"] for w in (monitor_ws, stage_ws, foh_ws)]

        item = create(foh, "Ny video", item_type="video")
        for w in (monitor_ws, stage_ws, foh_ws):
            snap = _next_snapshot(w)
            assert snap["revision"] > initial[0]
            assert any(i["title"] == "Ny video" for i in snap["items"])

        act(stage, item["id"], "request", "pending")
        _wait_for_status(foh_ws, item["id"], "requested", max_msgs=1)
        _wait_for_status(monitor_ws, item["id"], "requested", max_msgs=1)

        act(foh, item["id"], "ready", "requested")
        for w in (monitor_ws, stage_ws):
            _wait_for_status(w, item["id"], "ready", max_msgs=2)

        act(foh, item["id"], "start", "ready")
        for w in (monitor_ws, stage_ws, foh_ws):
            _wait_for_status(w, item["id"], "live", max_msgs=3)


def test_reconnect_receives_latest_state(foh, anon):
    with anon.websocket_connect("/ws") as ws:
        first = _next_snapshot(ws)
    # Forbindelsen er tabt, imens sker der ændringer
    item = create(foh, "Sket mens offline")
    act(foh, item["id"], "start")
    with anon.websocket_connect("/ws") as ws:
        snap = _next_snapshot(ws)
        assert snap["revision"] > first["revision"]
        assert next(i for i in snap["items"] if i["id"] == item["id"])["status"] == "live"


def test_websocket_is_read_only(foh, anon):
    item = create(foh)
    with anon.websocket_connect("/ws") as ws:
        _next_snapshot(ws)
        ws.send_json({"type": "action", "item_id": item["id"], "action": "start"})
    from .conftest import item_in_state
    assert item_in_state(anon, item["id"])["status"] == "pending"
