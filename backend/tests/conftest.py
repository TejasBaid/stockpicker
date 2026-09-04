"""Test harness.

Tests run against real Postgres (the schema uses JSONB and UUID types SQLite
cannot emulate). Each test runs inside a transaction that is rolled back, so
tests never see each other's rows and nothing is left behind.

They deliberately use the ``public`` schema rather than a dedicated test
schema: Neon's pooled endpoint shares server backends between clients, so a
session-level ``SET search_path`` leaks onto other connections and poisons
them. Rollback alone gives the isolation we need.

The production engine keeps a deliberately tiny pool (Render free tier), so
tests use their own engine with room to hold a connection per test.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings

test_engine = create_engine(
    get_settings().database_url, pool_size=5, max_overflow=5, pool_pre_ping=True, future=True
)


@pytest.fixture
def connection() -> Iterator[Connection]:
    conn = test_engine.connect()
    trans = conn.begin()
    yield conn
    trans.rollback()
    conn.close()


@pytest.fixture
def db(connection: Connection) -> Iterator[Session]:
    """Bound to the outer transaction with a restarting savepoint, so
    service-layer commit() calls cannot escape the test's rollback."""
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    from app.api.deps import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
