"""Domain exceptions mapped to HTTP responses in main.py."""

from __future__ import annotations


class AppError(Exception):
    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    status_code = 404


class AuthError(AppError):
    status_code = 401


class PermissionError_(AppError):
    status_code = 403


class ConflictError(AppError):
    status_code = 409


class DataUnavailableError(AppError):
    """Raised when a screen or backtest is requested before ingest has run."""

    status_code = 409


class ProviderError(AppError):
    status_code = 502


class BudgetExceededError(ProviderError):
    """The configured daily API call budget for a provider is exhausted."""

    status_code = 429
