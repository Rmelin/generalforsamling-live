"""Database-opsætning: SQLite i WAL-mode med eksplicitte transaktioner."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # pragma: no cover - simpel opsætning
        # Vi styrer selv BEGIN, så læsninger også sker i én konsistent transaktion.
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=FULL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):  # pragma: no cover - simpel opsætning
        conn.exec_driver_sql("BEGIN")

    return engine


class Database:
    """Samler engine, sessionfabrik og en skrivelås.

    Alle skrivninger serialiseres gennem `write()`, så samtidige handlinger
    aldrig ser en halvfærdig tilstand. Serveren kører med én proces.
    """

    def __init__(self, path: Path):
        self.path = path
        self.engine = make_engine(path)
        self.sessionmaker = sessionmaker(self.engine, expire_on_commit=False)
        self._lock = threading.Lock()

    def create_all(self) -> None:
        from . import models  # noqa: F401  (registrerer tabeller)

        Base.metadata.create_all(self.engine)

    @contextmanager
    def read(self) -> Iterator[Session]:
        with self.sessionmaker() as session, session.begin():
            yield session

    @contextmanager
    def write(self) -> Iterator[Session]:
        with self._lock:
            with self.sessionmaker() as session, session.begin():
                yield session

    def dispose(self) -> None:
        self.engine.dispose()
