"""Instruments, universes and daily price bars.

`instruments.symbol` is the plain NSE trading symbol (e.g. TATASTEEL). It is the
natural key across both providers: the Indian Stock API keys every endpoint off
it, and Groww's instrument master carries it as `trading_symbol`.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Instrument(Base, TimestampMixin):
    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String(40), primary_key=True)
    isin: Mapped[str | None] = mapped_column(String(12), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(120), index=True)
    industry: Mapped[str | None] = mapped_column(String(160), index=True)

    exchange: Mapped[str] = mapped_column(String(10), default="NSE", nullable=False)
    bse_code: Mapped[str | None] = mapped_column(String(20))
    groww_token: Mapped[str | None] = mapped_column(String(40))
    groww_symbol: Mapped[str | None] = mapped_column(String(60))
    lot_size: Mapped[int | None] = mapped_column(Integer)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Set when the Indian API has no coverage for this symbol, so ingest can skip it.
    fundamentals_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Universe(Base, TimestampMixin):
    """A named set of symbols: the Nifty 200 seed, or a user's watchlist."""

    __tablename__ = "universes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(60), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(400))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    members: Mapped[list[UniverseMember]] = relationship(
        back_populates="universe", cascade="all, delete-orphan"
    )


class UniverseMember(Base):
    __tablename__ = "universe_members"
    __table_args__ = (UniqueConstraint("universe_id", "symbol"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    universe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("universes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(
        ForeignKey("instruments.symbol", ondelete="CASCADE"), nullable=False, index=True
    )
    weight: Mapped[float | None] = mapped_column(Float)

    universe: Mapped[Universe] = relationship(back_populates="members")


class DailyBar(Base):
    """Split/bonus-adjusted daily OHLCV from Groww."""

    __tablename__ = "daily_bars"
    __table_args__ = (
        UniqueConstraint("symbol", "date"),
        Index("ix_daily_bars_symbol_date_desc", "symbol", "date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        ForeignKey("instruments.symbol", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
