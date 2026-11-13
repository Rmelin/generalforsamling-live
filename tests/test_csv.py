"""CSV-import og -eksport."""

from __future__ import annotations

import csv
import io

import pytest

from app import csvio

from .conftest import act, create


def _upload(client, text: str | bytes, mode="append", name="program.csv"):
    data = text.encode("utf-8") if isinstance(text, str) else text
    return client.post("/api/import", files={"file": (name, data, "text/csv")}, data={"mode": mode})


def _rows(resp_text: str):
    assert resp_text.startswith("﻿")  # BOM til Excel
    return list(csv.reader(io.StringIO(resp_text.lstrip("﻿")), delimiter=";"))


def test_export_contains_program(foh):
    a = create(foh, "Velkomst – Æbler", duration_seconds=300, technical_notes="Mikrofon; håndholdt")
    b = create(foh, "Film", item_type="video", duration_seconds=95, optional=True)
    act(foh, a["id"], "start")
    r = foh.get("/api/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = _rows(r.content.decode("utf-8"))
    assert rows[0] == csvio.EXPORT_COLUMNS
    assert rows[1][1:5] == ["Velkomst – Æbler", "Tale", "5:00", "Skal"]
    assert rows[1][6] == "Mikrofon; håndholdt"  # semikolon i tekst er korrekt citeret
    assert rows[1][7] == "Afvikles" and rows[1][8]  # status og starttid
    assert rows[2][1:5] == ["Film", "Video", "1:35", "Mulighed"]
    assert b["id"]


def test_export_requires_foh(stage, anon):
    assert stage.get("/api/export.csv").status_code == 403
    assert anon.get("/api/export.csv").status_code == 401


def test_import_append(foh):
    create(foh, "Eksisterende")
    text = (
        "titel;type;varighed;afvikling;beskrivelse;tekniske_noter\n"
        "Velkomst;Tale;5:00;Skal;Formanden;Talerpult\n"
        "Intro;Video;1:35;;;Video med lyd\n"
        "Hilsen;tale;5;Mulighed;;\n"
        "\n"
        "Debat;Andet;1:05:00;skal;;To mikrofoner\n"
    )
    r = _upload(foh, text)
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 4 and r.json()["removed"] == 0
    items = [i for i in foh.get("/api/state").json()["items"]]
    assert [i["title"] for i in items] == ["Eksisterende", "Velkomst", "Intro", "Hilsen", "Debat"]
    by = {i["title"]: i for i in items}
    assert by["Intro"]["item_type"] == "video" and by["Intro"]["duration_seconds"] == 95
    assert by["Hilsen"]["optional"] is True and by["Hilsen"]["duration_seconds"] == 300
    assert by["Debat"]["item_type"] == "other" and by["Debat"]["duration_seconds"] == 3900
    assert by["Velkomst"]["technical_notes"] == "Talerpult"
    events = [e for e in foh.get("/api/events").json()["events"] if e["details"] == "CSV-import"]
    assert len(events) == 4


def test_import_replace_keeps_live_and_history(foh):
    old = create(foh, "Gammel")
    live = create(foh, "Afvikles nu")
    done = create(foh, "Færdig")
    act(foh, done["id"], "start")
    act(foh, done["id"], "finish")
    act(foh, live["id"], "start")
    r = _upload(foh, "titel\nNy 1\nNy 2\n", mode="replace")
    assert r.status_code == 200 and r.json()["removed"] == 1
    titles = {i["title"]: i["status"] for i in foh.get("/api/state").json()["items"]}
    assert "Gammel" not in titles  # blødt slettet
    assert titles["Afvikles nu"] == "live" and titles["Færdig"] == "done"
    assert titles["Ny 1"] == "pending" and titles["Ny 2"] == "pending"
    assert old["id"]


def test_import_excel_cp1252_and_comma(foh):
    text = "Titel,Type,Varighed\nÅrsberetning,Tale,10\n"
    r = _upload(foh, text.encode("cp1252"))
    assert r.status_code == 200, r.text
    assert any(i["title"] == "Årsberetning" and i["duration_seconds"] == 600
               for i in foh.get("/api/state").json()["items"])


def test_import_errors_are_all_or_nothing(foh):
    text = (
        "titel;type;varighed;afvikling\n"
        "OK punkt;Tale;5:00;Skal\n"
        ";Tale;5:00;Skal\n"
        "Dans;Ballet;5;\n"
        "Lang;Tale;fem minutter;\n"
        "Valgfri;Tale;5;Måske\n"
    )
    r = _upload(foh, text)
    assert r.status_code == 422
    body = r.json()
    assert "Intet er importeret" in body["detail"]
    errs = " | ".join(body["errors"])
    assert "Linje 3" in errs and "titel mangler" in errs
    assert "Linje 4" in errs and "Ballet" in errs
    assert "Linje 5" in errs and "varighed" in errs
    assert "Linje 6" in errs and "Måske" in errs
    assert foh.get("/api/state").json()["items"] == []


def test_import_needs_title_header(foh):
    r = _upload(foh, "navnet;tid\nA;5\n")
    assert r.status_code == 422 and "titel" in r.json()["detail"]
    assert _upload(foh, "").status_code == 422


def test_export_import_roundtrip(foh):
    create(foh, "A", duration_seconds=125, technical_notes='Citat "her"; og semikolon')
    create(foh, "B", item_type="video", duration_seconds=60, optional=True)
    exported = foh.get("/api/export.csv").content
    r = _upload(foh, exported, mode="replace")
    assert r.status_code == 200 and r.json()["imported"] == 2
    items = [i for i in foh.get("/api/state").json()["items"] if i["status"] == "pending"]
    assert [(i["title"], i["item_type"], i["duration_seconds"], i["optional"], i["technical_notes"]) for i in items] == [
        ("A", "speech", 125, False, 'Citat "her"; og semikolon'),
        ("B", "video", 60, True, ""),
    ]


def test_import_permissions(stage, anon):
    assert _upload(stage, "titel\nX\n").status_code == 403
    assert _upload(anon, "titel\nX\n").status_code == 401


def test_template_can_be_imported(foh):
    tpl = foh.get("/api/export.csv?skabelon=1").content
    r = _upload(foh, tpl)
    assert r.status_code == 200 and r.json()["imported"] == 3


@pytest.mark.parametrize("value,secs", [
    ("5", 300), ("5,5", 330), ("5:30", 330), ("1:05:00", 3900), ("90s", 90), ("5 min", 300), ("", 0),
])
def test_parse_duration(value, secs):
    assert csvio.parse_duration(value) == secs
