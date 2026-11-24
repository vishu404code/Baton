"""Database layer: one SQLite file (WAL), one writer at a time.

Write sessions open every transaction with BEGIN IMMEDIATE, so SQLite itself serialises writers
(across threads and processes; others wait up to busy_timeout). That is what keeps the claim,
exactly-once and event-number guarantees race-free without Postgres row locks.
Read sessions use a plain BEGIN and never wait for the writer (WAL).

Rule: never open a second write session while one is open on the same thread (it would wait for
itself). Use read_session() for side reads.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def data_dir() -> Path:
    return Path(os.environ.get("BATON_DATA_DIR") or get_settings().baton_data_dir).expanduser().resolve()


def db_path() -> Path:
    return data_dir() / "baton.db"


_engines: dict[tuple[str, str], Engine] = {}
_lock = threading.Lock()


def _make_engine(path: Path, mode: str) -> Engine:
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):
        dbapi_conn.isolation_level = None  # we issue BEGIN ourselves (below)
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    begin = "BEGIN IMMEDIATE" if mode == "write" else "BEGIN"

    @event.listens_for(engine, "begin")
    def _on_begin(conn):
        conn.exec_driver_sql(begin)

    return engine


def _engine(mode: str) -> Engine:
    path = db_path()
    key = (str(path), mode)
    eng = _engines.get(key)
    if eng is None:
        with _lock:
            eng = _engines.get(key)
            if eng is None:
                path.parent.mkdir(parents=True, exist_ok=True)
                eng = _engines[key] = _make_engine(path, mode)
    return eng


def init_db() -> None:
    """Create all tables if they don't exist (idempotent)."""
    from app import models  # noqa: F401  (registers the tables on Base.metadata)

    eng = _engine("write")
    Base.metadata.create_all(eng)
    # Tiny additive migration for databases created before a column existed.
    with eng.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(context_entries)")}
        if cols and "is_demo" not in cols:
            conn.exec_driver_sql("ALTER TABLE context_entries ADD COLUMN is_demo BOOLEAN NOT NULL DEFAULT 0")


def reset_engines() -> None:
    """Dispose cached engines (used by tests after the data directory changes)."""
    with _lock:
        for eng in _engines.values():
            eng.dispose()
        _engines.clear()


def SessionLocal() -> Session:  # noqa: N802  (kept name: used across the codebase)
    """A write session (BEGIN IMMEDIATE)."""
    return Session(bind=_engine("write"), expire_on_commit=False)


def read_session() -> Session:
    """A read-only session: plain BEGIN, never blocked by the writer."""
    return Session(bind=_engine("read"), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def db_ok() -> bool:
    try:
        from sqlalchemy import text

        with read_session() as s:
            s.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
