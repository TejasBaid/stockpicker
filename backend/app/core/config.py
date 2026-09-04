"""Application settings, loaded from environment or backend/.env."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- infrastructure ---
    database_url: str = Field(alias="DATABASE_URL")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    secret_key: str = Field(default="dev-only-insecure-change-me", alias="SECRET_KEY")

    # --- providers ---
    groww_api_key: str = Field(default="", alias="GROWW_API_KEY")
    groww_secret: str = Field(default="", alias="GROWW_SECRET")
    indian_api_key: str = Field(default="", alias="INDIAN_API_KEY")
    indian_api_base: str = "https://stock.indianapi.in"

    # --- provider budgets (the Indian API publishes no quota headers, so we
    #     enforce our own ceiling and account for every call) ---
    indian_api_daily_budget: int = Field(default=400, alias="INDIAN_API_DAILY_BUDGET")
    groww_rate_per_sec: float = 8.0  # documented limit is 10/s; leave headroom
    indian_api_rate_per_sec: float = 2.0

    # --- auth ---
    session_ttl_days: int = 30
    cookie_name: str = "screener_session"
    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")

    cors_origins: list[str] = Field(default=["http://localhost:5173"], alias="CORS_ORIGINS")

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        """Neon hands out postgresql:// URLs; SQLAlchemy needs the psycopg driver."""
        return re.sub(r"^postgres(ql)?://", "postgresql+psycopg://", v)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
