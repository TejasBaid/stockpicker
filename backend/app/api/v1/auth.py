"""Auth routes: invite redemption, sign in, sign out, session introspection."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import AdminUser, CurrentUser, DbSession, client_user_agent
from app.core.config import get_settings
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


class SignUpRequest(BaseModel):
    invite_code: str = Field(min_length=4, max_length=200)
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=200)


class SignInRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    is_admin: bool


class InviteRequest(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    ttl_days: int = Field(default=14, ge=1, le=365)


class InviteOut(BaseModel):
    code: str
    expires_in_days: int


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_days * 86400,
        path="/",
    )


@router.post("/signup", response_model=UserOut, status_code=201)
def sign_up(
    payload: SignUpRequest,
    response: Response,
    db: DbSession,
    user_agent: Annotated[str | None, Depends(client_user_agent)] = None,
) -> UserOut:
    user = auth_service.redeem_invite(
        db,
        code=payload.invite_code.strip(),
        email=payload.email,
        display_name=payload.display_name,
        password=payload.password,
    )
    token = auth_service.create_session(db, user=user, user_agent=user_agent)
    _set_session_cookie(response, token)
    return UserOut.model_validate(user, from_attributes=True)


@router.post("/signin", response_model=UserOut)
def sign_in(
    payload: SignInRequest,
    response: Response,
    db: DbSession,
    user_agent: Annotated[str | None, Depends(client_user_agent)] = None,
) -> UserOut:
    user = auth_service.authenticate(db, email=payload.email, password=payload.password)
    token = auth_service.create_session(db, user=user, user_agent=user_agent)
    _set_session_cookie(response, token)
    return UserOut.model_validate(user, from_attributes=True)


@router.post("/signout", status_code=204)
def sign_out(
    response: Response,
    db: DbSession,
    screener_session: Annotated[str | None, Cookie(alias=settings.cookie_name)] = None,
) -> None:
    if screener_session:
        auth_service.revoke_session(db, screener_session)
    response.delete_cookie(settings.cookie_name, path="/")


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user, from_attributes=True)


@router.post("/invites", response_model=InviteOut, status_code=201)
def create_invite(payload: InviteRequest, db: DbSession, admin: AdminUser) -> InviteOut:
    """Admin-only. The plaintext code is returned once and never stored."""
    code = auth_service.create_invite(
        db, created_by=admin.id, label=payload.label, ttl_days=payload.ttl_days
    )
    return InviteOut(code=code, expires_in_days=payload.ttl_days)
