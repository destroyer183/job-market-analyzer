"""SQLite connection, session management, and declarative base.

The engine is intentionally *synchronous*: ``aiosqlite`` is not installed, and
SQLite serialises writes anyway, so async DB access buys very little here. Async
callers (the scraper, FastAPI routes) should reach the database through
``asyncio.to_thread`` so the event loop is never blocked.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

load_dotenv()

PROJECT_ROOT: Path = Path(__file__).resolve().parent
DEFAULT_DB_PATH: Path = PROJECT_ROOT / "jobs.db"

#: Override with e.g. ``DATABASE_URL=sqlite:///:memory:`` in tests.
DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")

_IS_SQLITE: bool = DATABASE_URL.startswith("sqlite")

engine: Engine = create_engine(
    DATABASE_URL,
    # SQLite guards against cross-thread reuse by default; we hand sessions to
    # worker threads via asyncio.to_thread, so that guard has to come off.
    connect_args={"check_same_thread": False} if _IS_SQLITE else {},
    echo=False,
    future=True,
)

SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine,
    autoflush=False,
    # Keeps attributes readable after commit() instead of triggering a reload.
    expire_on_commit=False,
)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection: object, connection_record: object) -> None:
    """Enable WAL and foreign keys on every new SQLite connection.

    Registered against the base ``Engine`` class, so the isinstance check is what
    keeps it from firing on a non-SQLite backend.
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


def init_db() -> None:
    """Create any missing tables.

    ``models`` is imported here rather than at module scope: ``models`` imports
    ``Base`` from this module, so a top-level import would be circular. The
    import is what registers the tables on ``Base.metadata``.
    """
    import models  # noqa: F401  # flat layout, not a package

    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session for scripts and tests.

    Commits on clean exit, rolls back on exception, always closes.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
