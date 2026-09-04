"""Auth flow: invites are required, sessions work, and isolation holds."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import AuthError, ConflictError
from app.services import auth as auth_service

GOOD_PASSWORD = "correct-horse-9-battery"


def _signup(client: TestClient, code: str, email: str = "first@example.com") -> object:
    return client.post(
        "/api/v1/auth/signup",
        json={
            "invite_code": code,
            "email": email,
            "display_name": "First User",
            "password": GOOD_PASSWORD,
        },
    )


def test_signup_requires_a_valid_invite(client: TestClient) -> None:
    r = _signup(client, "not-a-real-code")
    assert r.status_code == 401
    assert "invite code" in r.json()["detail"].lower()


def test_full_signup_signin_signout_cycle(client: TestClient, db: Session) -> None:
    code = auth_service.create_invite(db, label="test")

    r = _signup(client, code)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "first@example.com"
    assert body["is_admin"] is True  # first user in an empty system becomes admin

    assert client.get("/api/v1/auth/me").json()["email"] == "first@example.com"

    assert client.post("/api/v1/auth/signout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401

    r = client.post(
        "/api/v1/auth/signin",
        json={"email": "first@example.com", "password": GOOD_PASSWORD},
    )
    assert r.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200


def test_invite_cannot_be_reused(client: TestClient, db: Session) -> None:
    code = auth_service.create_invite(db)
    assert _signup(client, code, "a@example.com").status_code == 201
    r = _signup(client, code, "b@example.com")
    assert r.status_code == 409
    assert "already been used" in r.json()["detail"]


def test_wrong_password_is_rejected_without_leaking_account_existence(
    client: TestClient, db: Session
) -> None:
    code = auth_service.create_invite(db)
    _signup(client, code)

    wrong = client.post(
        "/api/v1/auth/signin", json={"email": "first@example.com", "password": "wrong-password-1"}
    )
    unknown = client.post(
        "/api/v1/auth/signin", json={"email": "nobody@example.com", "password": "wrong-password-1"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_weak_passwords_are_rejected(client: TestClient, db: Session) -> None:
    code = auth_service.create_invite(db)
    r = client.post(
        "/api/v1/auth/signup",
        json={
            "invite_code": code,
            "email": "weak@example.com",
            "display_name": "Weak",
            "password": "1234567890123",  # long enough, but all digits
        },
    )
    assert r.status_code == 409
    assert "letters" in r.json()["detail"]


def test_duplicate_email_is_rejected(client: TestClient, db: Session) -> None:
    _signup(client, auth_service.create_invite(db), "dupe@example.com")
    r = _signup(client, auth_service.create_invite(db), "dupe@example.com")
    assert r.status_code == 409


def test_only_admins_can_mint_invites(client: TestClient, db: Session) -> None:
    _signup(client, auth_service.create_invite(db), "admin@example.com")  # first == admin
    assert client.post("/api/v1/auth/invites", json={"label": "x"}).status_code == 201

    client.post("/api/v1/auth/signout")
    code2 = auth_service.create_invite(db)
    _signup(client, code2, "second@example.com")  # not the first user, so not admin
    r = client.post("/api/v1/auth/invites", json={"label": "y"})
    assert r.status_code == 403


def test_expired_invite_is_rejected(db: Session) -> None:
    code = auth_service.create_invite(db, ttl_days=1)
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.core.security import hash_token
    from app.db.models.auth import Invite

    inv = db.scalar(select(Invite).where(Invite.code_hash == hash_token(code)))
    assert inv is not None
    inv.expires_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()

    with pytest.raises(ConflictError, match="expired"):
        auth_service.redeem_invite(
            db, code=code, email="late@example.com", display_name="Late", password=GOOD_PASSWORD
        )


def test_revoked_session_stops_working(db: Session) -> None:
    code = auth_service.create_invite(db)
    user = auth_service.redeem_invite(
        db, code=code, email="rev@example.com", display_name="Rev", password=GOOD_PASSWORD
    )
    token = auth_service.create_session(db, user=user)
    assert auth_service.resolve_session(db, token) is not None
    auth_service.revoke_session(db, token)
    assert auth_service.resolve_session(db, token) is None


def test_deactivated_user_cannot_sign_in(db: Session) -> None:
    code = auth_service.create_invite(db)
    user = auth_service.redeem_invite(
        db, code=code, email="off@example.com", display_name="Off", password=GOOD_PASSWORD
    )
    user.is_active = False
    db.commit()
    with pytest.raises(AuthError, match="deactivated"):
        auth_service.authenticate(db, email="off@example.com", password=GOOD_PASSWORD)


def test_pooled_connections_resolve_tables_without_ambient_search_path() -> None:
    """Regression: Neon's -pooler shares server backends between clients, so a
    session-level `SET search_path` leaks and poisons other connections. The
    search path is pinned by a role default instead; this asserts a fresh
    pooled connection can actually find the tables."""
    import sqlalchemy as sa

    from app.db.session import engine

    for _ in range(4):
        with engine.connect() as c:
            assert c.execute(sa.text("select count(*) from users")).scalar() is not None
