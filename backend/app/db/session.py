"""Database engine and session management.

Tuned for Neon + a 512 MB Render instance: a small pool, pre-ping (Neon
auto-suspends idle compute after ~5 minutes), and recycling to avoid holding
connections a serverless Postgres has already dropped.

Neon's ``-pooler`` host is PgBouncer in transaction mode, so server-side
backends are shared between clients and consecutive statements can land on
different backends. Session-level state is therefore unreliable and leaky: no
code here may issue a session-level ``SET``. ``search_path`` is pinned instead
by a role default (``alter role ... set search_path to public``), and tests use
``SET LOCAL``, which is transaction-scoped and cannot escape into the pool.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    pool_size=2,
    max_overflow=3,
    pool_pre_ping=True,
    pool_recycle=280,
    future=True,
)



SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts and ingest jobs."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
