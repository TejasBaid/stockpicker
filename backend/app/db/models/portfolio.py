"""Portfolios, positions, exit plans, watchlists and alerts.

Positions are entered manually. Groww holdings are never read -- no holdings,
positions, orders or margin endpoint is called anywhere in this codebase.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

MONEY = Numeric(18, 4)


class Portfolio(Base, TimestampMixin):
    __tablename__ = "portfolios"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    base_currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    cash: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    positions: Mapped[list[Position]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )


class Position(Base, TimestampMixin):
    __tablename__ = "positions"
    __table_args__ = (Index("ix_positions_portfolio_symbol", "portfolio_id", "symbol"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(
        ForeignKey("instruments.symbol", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    avg_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    opened_on: Mapped[date] = mapped_column(Date, nullable=False)
    closed_on: Mapped[date | None] = mapped_column(Date)

    thesis: Mapped[str | None] = mapped_column(Text)
    conviction: Mapped[str | None] = mapped_column(String(20))
    target_weight: Mapped[float | None] = mapped_column(Numeric(8, 4))
    # Factor deciles at entry, so factor-decay exits can compare against them.
    entry_factors: Mapped[dict | None] = mapped_column(JSONB)
    review_on: Mapped[date | None] = mapped_column(Date)

    portfolio: Mapped[Portfolio] = relationship(back_populates="positions")
    trades: Mapped[list[Trade]] = relationship(
        back_populates="position", cascade="all, delete-orphan"
    )
    exit_plan: Mapped[ExitPlan | None] = relationship(
        back_populates="position", cascade="all, delete-orphan", uselist=False
    )


class Trade(Base, TimestampMixin):
    """An individual buy/sell lot. Kept separate from Position so Indian
    STCG/LTCG treatment can be computed per lot."""

    __tablename__ = "trades"
    __table_args__ = (Index("ix_trades_position_date", "position_id", "traded_on"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    position_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("positions.id", ondelete="CASCADE"), nullable=False
    )
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # BUY | SELL
    quantity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    traded_on: Mapped[date] = mapped_column(Date, nullable=False)
    fees: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    position: Mapped[Position] = relationship(back_populates="trades")


class ExitPlan(Base, TimestampMixin):
    """How this position should be exited, defined at entry rather than in a panic."""

    __tablename__ = "exit_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    position_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("positions.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    stop_type: Mapped[str | None] = mapped_column(String(20))  # atr | percent | trailing | none
    stop_value: Mapped[float | None] = mapped_column(Numeric(12, 4))
    stop_price: Mapped[Decimal | None] = mapped_column(MONEY)

    # [{"price": 250, "pct": 33}, ...]
    target_ladder: Mapped[list | None] = mapped_column(JSONB)
    time_stop_on: Mapped[date | None] = mapped_column(Date)

    # Exit when the factors the thesis rested on decay past these deciles.
    factor_decay_rules: Mapped[dict | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)

    position: Mapped[Position] = relationship(back_populates="exit_plan")


class Watchlist(Base, TimestampMixin):
    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("owner_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    items: Mapped[list[WatchlistItem]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan"
    )


class WatchlistItem(Base, TimestampMixin):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "symbol"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    watchlist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(
        ForeignKey("instruments.symbol", ondelete="CASCADE"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)

    watchlist: Mapped[Watchlist] = relationship(back_populates="items")


class Alert(Base, TimestampMixin):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_owner_triggered", "owner_id", "triggered_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str | None] = mapped_column(ForeignKey("instruments.symbol", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message: Mapped[str | None] = mapped_column(Text)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
