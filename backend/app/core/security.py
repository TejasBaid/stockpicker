"""Password hashing, invite codes and session tokens.

Sessions are opaque random tokens rather than JWTs: they are stored hashed, so
they can be revoked server-side, and there is no signing key to leak. Both
invite codes and session tokens are compared by hash, never in plaintext.
"""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()

SESSION_TOKEN_BYTES = 32
INVITE_CODE_BYTES = 12
MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return False


def generate_token(nbytes: int = SESSION_TOKEN_BYTES) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """SHA-256 is correct here: these are high-entropy random tokens, not
    low-entropy passwords, so a slow KDF buys nothing and costs latency on
    every authenticated request."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_invite_code() -> str:
    return secrets.token_urlsafe(INVITE_CODE_BYTES)


def validate_password_strength(password: str) -> str | None:
    """Return an error message, or None when acceptable."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if password.isdigit() or password.isalpha():
        return "Password must mix letters with numbers or symbols."
    return None
