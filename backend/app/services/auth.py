"""Authentication service: invite redemption, login, sessions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AuthError, ConflictError
from app.core.security import (
    generate_invite_code,
    generate_token,
    hash_password,
    hash_token,
    needs_rehash,
    validate_password_strength,
    verify_password,
)
from app.db.models.auth import Invite, User, UserSession

settings = get_settings()


def create_invite(
    db: Session,
    *,
    created_by: uuid.UUID | None = None,
    label: str | None = None,
    ttl_days: int = 14,
) -> str:
    """Create an invite and return the plaintext code -- shown once, never stored."""
    code = generate_invite_code()
    db.add(
        Invite(
            code_hash=hash_token(code),
            label=label,
            created_by=created_by,
            expires_at=datetime.now(UTC) + timedelta(days=ttl_days),
        )
    )
    db.commit()
    return code


def redeem_invite(db: Session, *, code: str, email: str, display_name: str, password: str) -> User:
    email = email.strip().lower()

    if (msg := validate_password_strength(password)) is not None:
        raise ConflictError(msg)

    invite = db.scalar(select(Invite).where(Invite.code_hash == hash_token(code)))
    if invite is None:
        raise AuthError("That invite code is not valid.")
    if invite.redeemed_at is not None:
        raise ConflictError("That invite code has already been used.")
    if invite.expires_at is not None and invite.expires_at < datetime.now(UTC):
        raise ConflictError("That invite code has expired.")

    if db.scalar(select(User).where(User.email == email)) is not None:
        raise ConflictError("An account with that email already exists.")

    # First user in the system becomes the admin.
    is_first = db.scalar(select(User.id).limit(1)) is None

    user = User(
        email=email,
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        is_admin=is_first,
    )
    db.add(user)
    db.flush()

    invite.redeemed_at = datetime.now(UTC)
    invite.redeemed_by = user.id
    db.commit()
    return user


def authenticate(db: Session, *, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not verify_password(password, user.password_hash):
        # Same message either way: never reveal whether an email is registered.
        raise AuthError("Incorrect email or password.")
    if not user.is_active:
        raise AuthError("This account has been deactivated.")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = datetime.now(UTC)
    db.commit()
    return user


def create_session(db: Session, *, user: User, user_agent: str | None = None) -> str:
    """Create a session and return the plaintext token for the cookie."""
    token = generate_token()
    now = datetime.now(UTC)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            created_at=now,
            expires_at=now + timedelta(days=settings.session_ttl_days),
            user_agent=(user_agent or "")[:400] or None,
        )
    )
    db.commit()
    return token


def resolve_session(db: Session, token: str) -> User | None:
    row = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if row is None or row.expires_at < datetime.now(UTC):
        return None
    user = db.get(User, row.user_id)
    return user if user is not None and user.is_active else None


def revoke_session(db: Session, token: str) -> None:
    row = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if row is not None:
        db.delete(row)
        db.commit()


def purge_expired_sessions(db: Session) -> int:
    rows = db.scalars(select(UserSession).where(UserSession.expires_at < datetime.now(UTC))).all()
    for r in rows:
        db.delete(r)
    db.commit()
    return len(rows)
