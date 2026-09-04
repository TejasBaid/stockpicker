"""Saved strategies and watchlists."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.market import Instrument
from app.services.auth import create_invite, create_session, redeem_invite

SYMBOL = "ZZWATCH"


@pytest.fixture
def signed_in(client: TestClient, db: Session) -> TestClient:
    user = redeem_invite(
        db,
        code=create_invite(db),
        email=f"st-{uuid.uuid4().hex[:8]}@example.com",
        display_name="ST",
        password="correct-horse-9-battery",
    )
    client.cookies.set("screener_session", create_session(db, user=user))
    return client


def test_saving_a_strategy_bumps_the_version(signed_in: TestClient) -> None:
    body = {"name": "My blend", "weights": {"roe": 0.6, "earnings_yield": 0.4}}
    first = signed_in.post("/api/v1/strategies", json=body)
    assert first.status_code == 201
    assert first.json()["version"] == 1

    second = signed_in.post("/api/v1/strategies", json=body)
    assert second.json()["version"] == 2
    # The list shows one entry, at the latest version -- not two.
    listing = signed_in.get("/api/v1/strategies").json()
    mine = [s for s in listing if s["slug"] == "my-blend"]
    assert len(mine) == 1
    assert mine[0]["version"] == 2


def test_unknown_factors_are_rejected(signed_in: TestClient) -> None:
    r = signed_in.post("/api/v1/strategies", json={"name": "Bad", "weights": {"not_a_factor": 1.0}})
    assert r.status_code == 422
    assert "Unknown factor" in r.json()["detail"]


def test_empty_weights_are_rejected(signed_in: TestClient) -> None:
    r = signed_in.post("/api/v1/strategies", json={"name": "Empty", "weights": {}})
    assert r.status_code == 422


def test_deleting_removes_every_version(signed_in: TestClient) -> None:
    body = {"name": "Doomed", "weights": {"roe": 1.0}}
    signed_in.post("/api/v1/strategies", json=body)
    created = signed_in.post("/api/v1/strategies", json=body).json()
    assert signed_in.delete(f"/api/v1/strategies/{created['id']}").status_code == 204
    assert not [s for s in signed_in.get("/api/v1/strategies").json() if s["slug"] == "doomed"]


def test_strategies_are_private_to_their_owner(
    client: TestClient, db: Session, signed_in: TestClient
) -> None:
    signed_in.post("/api/v1/strategies", json={"name": "Private", "weights": {"roe": 1.0}})

    other = redeem_invite(
        db,
        code=create_invite(db),
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Other",
        password="correct-horse-9-battery",
    )
    signed_in.cookies.set("screener_session", create_session(db, user=other))
    assert not [s for s in signed_in.get("/api/v1/strategies").json() if s["slug"] == "private"]


def test_watchlist_add_and_remove(signed_in: TestClient, db: Session) -> None:
    db.add(Instrument(symbol=SYMBOL, name="Watch Co", sector="Tech", exchange="NSE"))
    db.commit()

    assert signed_in.post("/api/v1/watchlist/items", json={"symbol": SYMBOL}).status_code == 201
    data = signed_in.get("/api/v1/watchlist").json()
    assert [i["symbol"] for i in data["items"]] == [SYMBOL]

    # A duplicate is a conflict, not a silent no-op.
    dupe = signed_in.post("/api/v1/watchlist/items", json={"symbol": SYMBOL})
    assert dupe.status_code == 409

    assert signed_in.delete(f"/api/v1/watchlist/items/{SYMBOL}").status_code == 204
    assert signed_in.get("/api/v1/watchlist").json()["items"] == []


def test_watchlist_rejects_unknown_symbols(signed_in: TestClient) -> None:
    r = signed_in.post("/api/v1/watchlist/items", json={"symbol": "NOSUCHTICKER"})
    assert r.status_code == 404
