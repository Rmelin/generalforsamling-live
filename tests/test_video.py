"""Tale/Andet med video, QLab-cue og "Indlæst i QLab"."""

from __future__ import annotations

from .conftest import create, item_in_state


def _qlab(client, item_id, loaded):
    return client.post(f"/api/items/{item_id}/qlab", json={"loaded": loaded})


def test_speech_with_video(foh):
    item = create(foh, "Beretning", has_video=True, qlab_cue="2")
    assert item["item_type"] == "speech"
    assert item["has_video"] is True
    assert item["qlab_cue"] == "2"
    assert item["qlab_loaded"] is False


def test_video_type_always_has_video_and_plain_speech_has_none(foh):
    assert create(foh, "Film", item_type="video")["has_video"] is True
    assert create(foh, "Tale")["has_video"] is False


def test_edit_video_flag_and_cue(foh):
    item = create(foh, "Pris", item_type="other")
    r = foh.patch(f"/api/items/{item['id']}",
                  json={"expected_version": item["version"], "has_video": True, "qlab_cue": " 7 "})
    assert r.status_code == 200, r.text
    assert r.json()["item"]["has_video"] is True
    assert r.json()["item"]["qlab_cue"] == "7"


def test_mark_loaded_in_qlab(foh):
    item = create(foh, "Beretning", has_video=True)
    r = _qlab(foh, item["id"], True)
    assert r.status_code == 200 and r.json()["changed"] is True
    assert item_in_state(foh, item["id"])["qlab_loaded"] is True
    # Idempotent
    assert _qlab(foh, item["id"], True).json()["changed"] is False
    assert _qlab(foh, item["id"], False).json()["changed"] is True
    assert item_in_state(foh, item["id"])["qlab_loaded"] is False
    events = [e for e in foh.get("/api/events").json()["events"] if e["action"] == "qlab"]
    assert [e["details"] for e in events] == ["Ikke indlæst i QLab", "Indlæst i QLab"]


def test_qlab_mark_does_not_conflict_with_open_editor(foh):
    """QLab-markeringen må ikke give "ændret af en anden" for den, der redigerer punktet."""
    item = create(foh, "Beretning", has_video=True)
    _qlab(foh, item["id"], True)
    r = foh.patch(f"/api/items/{item['id']}", json={"expected_version": item["version"], "title": "Ny titel"})
    assert r.status_code == 200, r.text


def test_qlab_is_foh_only(foh, stage, anon):
    item = create(foh, "Film", item_type="video")
    assert _qlab(stage, item["id"], True).status_code == 403
    assert _qlab(anon, item["id"], True).status_code == 401
    assert _qlab(foh, 99999, True).status_code == 404


def test_cue_length_is_limited(foh):
    r = foh.post("/api/items", json={"title": "X", "has_video": True, "qlab_cue": "x" * 41})
    assert r.status_code == 422
