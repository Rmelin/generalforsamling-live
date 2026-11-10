"""Forretningslogik: alle læsninger og skrivninger af afviklingspunkter.

Serveren er autoritativ. Hver skrivning sker i én transaktion under en
skrivelås og øger en global revisionstæller, som klienterne bruger til at
afvise forældede snapshots.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import state as st
from .db import Database
from .models import Event, Item, Meta, utcnow
from .schemas import ItemCreate, ItemUpdate


class ServiceError(Exception):
    status_code = 400
    code = "error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(ServiceError):
    status_code = 404
    code = "not_found"


class Conflict(ServiceError):
    status_code = 409
    code = "conflict"


class Forbidden(ServiceError):
    status_code = 403
    code = "forbidden"


@dataclass
class Actor:
    role: str
    username: str

    @property
    def label(self) -> str:
        return f"{self.role}:{self.username}"


# ---------------------------------------------------------------- serialisering


def iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat(timespec="milliseconds") + "Z"


def item_to_dict(item: Item) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "item_type": item.item_type,
        "description": item.description or "",
        "technical_notes": item.technical_notes or "",
        "duration_seconds": item.duration_seconds,
        "optional": bool(item.optional),
        "status": item.status,
        "sort_order": item.sort_order,
        "version": item.version,
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
        "requested_at": iso(item.requested_at),
        "ready_at": iso(item.ready_at),
        "started_at": iso(item.started_at),
        "ended_at": iso(item.ended_at),
    }


def event_to_dict(ev: Event) -> dict[str, Any]:
    return {
        "id": ev.id,
        "created_at": iso(ev.created_at),
        "item_id": ev.item_id,
        "item_title": ev.item_title,
        "action": ev.action,
        "from_status": ev.from_status,
        "to_status": ev.to_status,
        "actor": ev.actor,
        "details": ev.details,
    }


# ---------------------------------------------------------------- meta / revision


def _meta_get(s: Session, key: str) -> Optional[str]:
    row = s.get(Meta, key)
    return row.value if row else None


def _meta_set(s: Session, key: str, value: str) -> None:
    row = s.get(Meta, key)
    if row is None:
        s.add(Meta(key=key, value=value))
    else:
        row.value = value


def init_meta(db: Database) -> None:
    with db.write() as s:
        if _meta_get(s, "db_id") is None:
            _meta_set(s, "db_id", uuid.uuid4().hex)
        if _meta_get(s, "revision") is None:
            _meta_set(s, "revision", "0")


def _bump_revision(s: Session) -> int:
    rev = int(_meta_get(s, "revision") or "0") + 1
    _meta_set(s, "revision", str(rev))
    return rev


def _log(
    s: Session,
    actor: Actor,
    action: str,
    item: Optional[Item],
    from_status: Optional[str] = None,
    to_status: Optional[str] = None,
    details: str = "",
) -> None:
    s.add(
        Event(
            created_at=utcnow(),
            item_id=item.id if item else None,
            item_title=item.title if item else "",
            action=action,
            from_status=from_status,
            to_status=to_status,
            actor=actor.label,
            details=details,
        )
    )


# ---------------------------------------------------------------- læsning


def snapshot(db: Database) -> dict[str, Any]:
    """Komplet, konsistent tilstand – sendes til alle klienter."""
    with db.read() as s:
        items = s.scalars(
            select(Item).where(Item.deleted.is_(False)).order_by(Item.sort_order, Item.id)
        ).all()
        return {
            "type": "snapshot",
            "db_id": _meta_get(s, "db_id"),
            "revision": int(_meta_get(s, "revision") or "0"),
            "server_time": iso(utcnow()),
            "items": [item_to_dict(i) for i in items],
        }


def list_events(db: Database, limit: int = 300) -> list[dict[str, Any]]:
    with db.read() as s:
        events = s.scalars(select(Event).order_by(Event.id.desc()).limit(limit)).all()
        return [event_to_dict(e) for e in events]


def _get_item(s: Session, item_id: int) -> Item:
    item = s.get(Item, item_id)
    if item is None or item.deleted:
        raise NotFound("Punktet findes ikke.")
    return item


# ---------------------------------------------------------------- skrivning


def create_item(db: Database, data: ItemCreate, actor: Actor) -> dict[str, Any]:
    with db.write() as s:
        max_order = s.scalar(select(func.max(Item.sort_order))) or 0
        now = utcnow()
        item = Item(
            title=data.title,
            item_type=data.item_type,
            description=data.description,
            technical_notes=data.technical_notes,
            duration_seconds=data.duration_seconds,
            optional=data.optional,
            status=st.PENDING,
            sort_order=max_order + 10,
            version=1,
            created_at=now,
            updated_at=now,
        )
        s.add(item)
        s.flush()
        _log(s, actor, "create", item, None, st.PENDING)
        _bump_revision(s)
        return item_to_dict(item)


def update_item(db: Database, item_id: int, data: ItemUpdate, actor: Actor) -> dict[str, Any]:
    with db.write() as s:
        item = _get_item(s, item_id)
        if item.version != data.expected_version:
            raise Conflict(
                "Punktet er blevet ændret af en anden i mellemtiden. "
                "Den nyeste version er hentet – kontrollér og gem igen."
            )
        changes = data.model_dump(exclude_unset=True, exclude={"expected_version"})
        changed_fields = []
        for field, value in changes.items():
            if value is None:
                continue
            if getattr(item, field) != value:
                setattr(item, field, value)
                changed_fields.append(field)
        if not changed_fields:
            return item_to_dict(item)
        item.version += 1
        item.updated_at = utcnow()
        _log(s, actor, "edit", item, item.status, item.status, ", ".join(changed_fields))
        _bump_revision(s)
        return item_to_dict(item)


def delete_item(db: Database, item_id: int, actor: Actor) -> None:
    """Blød sletning: punktet skjules, men forbliver i databasen og loggen."""
    with db.write() as s:
        item = _get_item(s, item_id)
        if item.status == st.LIVE:
            raise Conflict("Et punkt, der afvikles, kan ikke slettes. Afslut det først.")
        item.deleted = True
        item.version += 1
        item.updated_at = utcnow()
        _log(s, actor, "delete", item, item.status, None)
        _bump_revision(s)


def apply_action(
    db: Database,
    item_id: int,
    action: str,
    actor: Actor,
    expected_status: Optional[str] = None,
) -> tuple[dict[str, Any], bool]:
    """Udfør en statusovergang. Returnerer (punkt, ændret?).

    - Idempotent: står punktet allerede i målstatus, sker intet.
    - `expected_status` afviser handlinger baseret på forældet tilstand.
    """
    if action not in st.ACTIONS:
        raise NotFound(f"Ukendt handling: {action}")
    if not st.role_may(action, actor.role):
        raise Forbidden("Din rolle må ikke udføre denne handling.")

    with db.write() as s:
        item = _get_item(s, item_id)
        current = item.status
        target = st.target_status(action)

        if current == target:
            return item_to_dict(item), False

        if expected_status is not None and expected_status != current:
            raise Conflict(
                f"Punktet har skiftet status til '{st.STATUS_LABELS.get(current, current)}', "
                "før din handling nåede frem. Visningen er opdateret."
            )
        try:
            st.resolve_transition(action, actor.role, current)
        except st.TransitionError as exc:
            if exc.forbidden:
                raise Forbidden(exc.message) from exc
            raise Conflict(exc.message) from exc

        now = utcnow()
        if action == "start":
            # Kun ét punkt kan afvikles ad gangen: et igangværende punkt afsluttes.
            others = s.scalars(
                select(Item).where(
                    Item.status == st.LIVE, Item.deleted.is_(False), Item.id != item.id
                )
            ).all()
            for other in others:
                other.status = st.DONE
                other.ended_at = now
                other.updated_at = now
                other.version += 1
                _log(s, actor, "finish", other, st.LIVE, st.DONE,
                     f"Automatisk afsluttet, da '{item.title}' blev startet")

        item.status = target
        item.version += 1
        item.updated_at = now
        if action == "request":
            item.requested_at = now
            item.ready_at = None
        elif action == "ready":
            item.ready_at = now
            if item.requested_at is None:
                item.requested_at = now
        elif action == "withdraw":
            item.requested_at = None
            item.ready_at = None
        elif action == "start":
            item.started_at = now
            item.ended_at = None
        elif action in ("finish", "cancel"):
            if current == st.LIVE:
                item.ended_at = now
        elif action == "reopen":
            item.requested_at = None
            item.ready_at = None

        _log(s, actor, action, item, current, target)
        _bump_revision(s)
        return item_to_dict(item), True


def move_item(db: Database, item_id: int, direction: str, actor: Actor) -> bool:
    """Flyt et aktivt punkt én plads op eller ned blandt de aktive punkter."""
    with db.write() as s:
        item = _get_item(s, item_id)
        active = s.scalars(
            select(Item)
            .where(Item.deleted.is_(False), Item.status.in_(st.ACTIVE_STATUSES))
            .order_by(Item.sort_order, Item.id)
        ).all()
        ids = [i.id for i in active]
        if item.id not in ids:
            raise Conflict("Kun aktive punkter kan flyttes.")
        idx = ids.index(item.id)
        swap_idx = idx - 1 if direction == "up" else idx + 1
        if swap_idx < 0 or swap_idx >= len(active):
            return False
        other = active[swap_idx]
        if item.sort_order == other.sort_order:
            # Sørg for unikke sorteringsværdier
            for n, it in enumerate(active):
                it.sort_order = (n + 1) * 10
        item.sort_order, other.sort_order = other.sort_order, item.sort_order
        now = utcnow()
        for it in (item, other):
            it.version += 1
            it.updated_at = now
        _log(s, actor, "move", item, item.status, item.status,
             "op" if direction == "up" else "ned")
        _bump_revision(s)
        return True


def is_empty(db: Database) -> bool:
    with db.read() as s:
        return (s.scalar(select(func.count(Item.id))) or 0) == 0
