"""Precomputed factor values.

Factors are computed nightly by the worker, never in the request path. A screen
is then an indexed SELECT plus a weighted sum over ~200 rows, which is what
makes the platform usable on a 512 MB / 0.1 CPU instance.
"""

from __future__ import annotations

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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FactorValue(Base):
    __tablename__ = "factor_values"
    __table_args__ = (
        UniqueConstraint("symbol", "as_of", "factor"),
        Index("ix_factor_values_asof_factor", "as_of", "factor"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        ForeignKey("instruments.symbol", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    factor: Mapped[str] = mapped_column(String(60), nullable=False)

    raw: Mapped[float | None] = mapped_column(Float)
    zscore: Mapped[float | None] = mapped_column(Float)
    sector_zscore: Mapped[float | None] = mapped_column(Float)
    percentile: Mapped[float | None] = mapped_column(Float)
    decile: Mapped[int | None] = mapped_column(Integer)
    # True when the underlying fundamental used an estimated known_on date.
    estimated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class FactorCoverage(Base):
    """Per-factor coverage for a run, so a factor computed on 40% of the
    universe is never silently trusted."""

    __tablename__ = "factor_coverage"
    __table_args__ = (UniqueConstraint("as_of", "factor"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    factor: Mapped[str] = mapped_column(String(60), nullable=False)
    n_total: Mapped[int] = mapped_column(Integer, nullable=False)
    n_covered: Mapped[int] = mapped_column(Integer, nullable=False)
    coverage_pct: Mapped[float] = mapped_column(Float, nullable=False)
