"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AuthError, PermissionError_
from app.db.models.auth import User
from app.db.session import get_db
from app.services import auth as auth_service

settings = get_settings()

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    screener_session: Annotated[str | None, Cookie(alias=settings.cookie_name)] = None,
) -> User:
    if not screener_session:
        raise AuthError("Not signed in.")
    user = auth_service.resolve_session(db, screener_session)
    if user is None:
        raise AuthError("Your session has expired. Please sign in again.")
    return user


def get_optional_user(
    db: DbSession,
    screener_session: Annotated[str | None, Cookie(alias=settings.cookie_name)] = None,
) -> User | None:
    if not screener_session:
        return None
    return auth_service.resolve_session(db, screener_session)


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise PermissionError_("Administrator access required.")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def client_user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")
