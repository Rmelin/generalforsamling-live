"""Import og eksport af programmet som CSV.

Eksport bruger semikolon og UTF-8 med BOM, så filen åbner korrekt i dansk Excel.
Import accepterer semikolon, komma eller tabulator, UTF-8 eller Windows-1252
(Excels "CSV (semikolonsepareret)"), og danske eller engelske overskrifter.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from . import state as st
from .schemas import ItemCreate

MAX_BYTES = 1_000_000
MAX_ROWS = 1000

EXPORT_COLUMNS = [
    "nr", "titel", "type", "varighed", "afvikling", "beskrivelse", "tekniske_noter",
    "status", "start", "slut", "faktisk_varighed",
]

TYPE_LABEL = {"speech": "Tale", "video": "Video", "other": "Andet"}


# ---------------------------------------------------------------- hjælpere


def fmt_duration(sec: Optional[int]) -> str:
    if not sec:
        return ""
    sec = int(sec)
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _local(iso: Optional[str], tz: ZoneInfo) -> str:
    if not iso:
        return ""
    dt = datetime.fromisoformat(iso.rstrip("Z")).replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")


def _actual(it: dict[str, Any]) -> str:
    if not (it.get("started_at") and it.get("ended_at")):
        return ""
    a = datetime.fromisoformat(it["started_at"].rstrip("Z"))
    b = datetime.fromisoformat(it["ended_at"].rstrip("Z"))
    return fmt_duration(max(0, int((b - a).total_seconds()))) or "0:00"


# ---------------------------------------------------------------- eksport


def export_csv(items: list[dict[str, Any]], tz_name: str = "Europe/Copenhagen") -> str:
    tz = ZoneInfo(tz_name)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(EXPORT_COLUMNS)
    for n, it in enumerate(items, start=1):
        w.writerow([
            n,
            it["title"],
            TYPE_LABEL.get(it["item_type"], it["item_type"]),
            fmt_duration(it["duration_seconds"]),
            "Mulighed" if it.get("optional") else "Skal",
            it.get("description", ""),
            it.get("technical_notes", ""),
            st.STATUS_LABELS.get(it["status"], it["status"]),
            _local(it.get("started_at"), tz),
            _local(it.get("ended_at"), tz),
            _actual(it),
        ])
    return "﻿" + buf.getvalue()


def template_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["titel", "type", "varighed", "afvikling", "beskrivelse", "tekniske_noter"])
    w.writerow(["Velkomst ved formanden", "Tale", "5:00", "Skal", "", "Talerpult-mikrofon"])
    w.writerow(["Intro-video", "Video", "1:35", "Skal", "Åbningsfilm", "Video med lyd – klargør afspiller"])
    w.writerow(["Hilsen fra samarbejdspartner", "Tale", "5", "Mulighed", "Kun hvis tiden tillader det", ""])
    return "﻿" + buf.getvalue()


# ---------------------------------------------------------------- import

_HEADER_ALIASES = {
    "title": {"titel", "title", "navn", "punkt", "indslag"},
    "item_type": {"type", "indslagstype", "kategori"},
    "duration": {"varighed", "duration", "tid", "laengde", "længde", "forventet varighed"},
    "optional": {"afvikling", "mulighed", "valgfri", "optional", "skal/mulighed"},
    "description": {"beskrivelse", "description", "info"},
    "technical_notes": {"tekniske_noter", "tekniske noter", "teknik", "noter", "technical_notes",
                        "technical notes", "teknisk note"},
}

_TYPE_VALUES = {
    "speech": {"tale", "speech", "t", "taler"},
    "video": {"video", "film", "v"},
    "other": {"andet", "other", "a", "øvrigt", "oevrigt"},
}

_OPTIONAL_TRUE = {"mulighed", "valgfri", "valgfrit", "ja", "j", "x", "1", "true", "yes", "optional"}
_OPTIONAL_FALSE = {"", "skal", "skal afvikles", "nej", "n", "0", "false", "no", "obligatorisk"}


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", h.replace("\ufeff", "").strip().strip('"').lower())


def _field_for(header: str) -> Optional[str]:
    h = _norm(header)
    for field, names in _HEADER_ALIASES.items():
        if h in names or h.replace(" ", "_") in names or h.replace("_", " ") in names:
            return field
    return None


def parse_duration(value: str) -> int:
    """'5' = 5 min, '5,5' = 5½ min, '5:30', '1:05:00', '90s', '5 min'."""
    v = value.strip().lower().replace(",", ".")
    if not v:
        return 0
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(s|sek|sekunder|m|min|minutter|t|timer|h)?", v)
    if m:
        num = float(m.group(1))
        unit = m.group(2) or "min"
        factor = 1 if unit.startswith("s") else 3600 if unit in ("t", "timer", "h") else 60
        return int(round(num * factor))
    parts = v.split(":")
    if 2 <= len(parts) <= 3 and all(p.isdigit() for p in parts):
        total = 0
        for p in parts:
            total = total * 60 + int(p)
        return total
    raise ValueError(f"ugyldig varighed '{value}' (brug fx 5:00 eller 5)")


def _parse_type(value: str) -> str:
    v = value.strip().lower()
    if not v:
        return "speech"
    for key, names in _TYPE_VALUES.items():
        if v in names:
            return key
    raise ValueError(f"ukendt type '{value}' (brug Tale, Video eller Andet)")


def _parse_optional(value: str) -> bool:
    v = value.strip().lower()
    if v in _OPTIONAL_TRUE:
        return True
    if v in _OPTIONAL_FALSE:
        return False
    raise ValueError(f"ukendt afvikling '{value}' (brug Skal eller Mulighed)")


def decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def _delimiter(first_line: str) -> str:
    counts = {d: first_line.count(d) for d in (";", ",", "\t")}
    best = max(counts, key=counts.get)
    return best if counts[best] else ";"


class CsvImportError(Exception):
    def __init__(self, message: str, errors: list[str]):
        super().__init__(message)
        self.message = message
        self.errors = errors


def parse_csv(text: str) -> list[ItemCreate]:
    """Fortolk CSV-tekst. Rejser CsvImportError med linjenumre ved fejl.

    Alt eller intet: er én linje forkert, importeres ingenting.
    """
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        raise CsvImportError("Filen er tom.", [])
    delim = _delimiter(lines[0])
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delim)
    header = next(reader)
    mapping = {i: _field_for(h) for i, h in enumerate(header)}
    if "title" not in mapping.values():
        raise CsvImportError(
            "Første linje skal være overskrifter og indeholde en kolonne 'titel' "
            "(fx titel;type;varighed;afvikling;beskrivelse;tekniske_noter).",
            [],
        )

    items: list[ItemCreate] = []
    errors: list[str] = []
    for lineno, row in enumerate(reader, start=2):
        if not any(c.strip() for c in row):
            continue  # tom linje
        if len(items) + len(errors) >= MAX_ROWS:
            raise CsvImportError(f"For mange linjer (højst {MAX_ROWS}).", [])
        values: dict[str, str] = {}
        for i, cell in enumerate(row):
            field = mapping.get(i)
            if field and field not in values:
                values[field] = cell.strip()
        try:
            data = ItemCreate(
                title=values.get("title", ""),
                item_type=_parse_type(values.get("item_type", "")),
                duration_seconds=parse_duration(values.get("duration", "")),
                optional=_parse_optional(values.get("optional", "")),
                description=values.get("description", ""),
                technical_notes=values.get("technical_notes", ""),
            )
            items.append(data)
        except ValueError as exc:
            if isinstance(exc, ValidationError):
                msgs = []
                for e in exc.errors():
                    loc = e["loc"][0] if e["loc"] else ""
                    if loc == "title":
                        msgs.append("titel mangler" if not values.get("title") else "titel er for lang")
                    elif loc == "duration_seconds":
                        msgs.append("varighed er for lang (højst 24 timer)")
                    else:
                        msgs.append(f"{loc}: {e['msg']}")
                errors.append(f"Linje {lineno}: " + "; ".join(msgs))
            else:
                errors.append(f"Linje {lineno}: {exc}")
    if errors:
        shown = errors[:20]
        if len(errors) > 20:
            shown.append(f"… og {len(errors) - 20} fejl mere")
        raise CsvImportError(f"Intet er importeret – {len(errors)} linje(r) har fejl.", shown)
    if not items:
        raise CsvImportError("Filen indeholder ingen punkter.", [])
    return items
