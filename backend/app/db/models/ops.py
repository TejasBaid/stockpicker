"""Operational tables: provider quota accounting and ingest run history.

The Indian Stock API publishes no quota headers and its pricing page is
JS-gated, so we account for every call ourselves and enforce a configured
daily ceiling.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ProviderCallDaily(Base):
    """Rolled-up call counts per provider per day, for budget enforcement."""

    __tablename__ = "provider_calls_daily"
    __table_args__ = (UniqueConstraint("provider", "call_date", "endpoint"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    call_date: Mapped[date] = mapped_column(Date, nullable=False)
    endpoint: Mapped[str] = mapped_column(String(80), nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class IngestRun(Base, TimestampMixin):
    __tablename__ = "ingest_runs"
    __table_args__ = (Index("ix_ingest_runs_job_started", "job", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    symbols_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    symbols_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_written: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    api_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
