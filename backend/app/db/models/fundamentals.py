"""Fundamental data with point-in-time discipline.

Every row carries `known_on`: the date the market could first have known this
information. Screens and backtests filter on it, which is what keeps backtest
results honest.

`/stock` returns a `StatementDate` field but it is broken upstream -- it reports
the same date for every fiscal period regardless of `EndDate`. So `known_on` is
derived from `/stock_forecasts.ActualReportDate` where available, and otherwise
from the SEBI LODR Reg. 33 filing deadline (45 days after an interim period,
60 days after an annual one). Rows using the fallback are flagged
`known_on_estimated` so the UI can say so.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class FundamentalSnapshot(Base, TimestampMixin):
    """Append-only snapshot of the ~145 metrics `/stock` returns.

    Curated metrics get typed columns because factors and the research page read
    them constantly; the untouched payload is kept in `raw` so a remapping never
    requires refetching (and never costs API quota).
    """

    __tablename__ = "fundamental_snapshots"
    __table_args__ = (
        UniqueConstraint("symbol", "snapshot_date"),
        Index("ix_fundamental_snapshots_symbol_known", "symbol", "known_on"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        ForeignKey("instruments.symbol", ondelete="CASCADE"), nullable=False
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    known_on: Mapped[date] = mapped_column(Date, nullable=False)
    known_on_estimated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- valuation ---
    pe_ttm: Mapped[float | None] = mapped_column(Float)
    pe_fy: Mapped[float | None] = mapped_column(Float)
    pe_normalized_fy: Mapped[float | None] = mapped_column(Float)
    pb_fy: Mapped[float | None] = mapped_column(Float)
    pb_q: Mapped[float | None] = mapped_column(Float)
    price_to_tangible_book_fy: Mapped[float | None] = mapped_column(Float)
    ps_ttm: Mapped[float | None] = mapped_column(Float)
    ps_fy: Mapped[float | None] = mapped_column(Float)
    peg: Mapped[float | None] = mapped_column(Float)
    dividend_yield: Mapped[float | None] = mapped_column(Float)
    dividend_yield_5y_avg: Mapped[float | None] = mapped_column(Float)
    price_to_fcf_fy: Mapped[float | None] = mapped_column(Float)
    price_to_cashflow_ttm: Mapped[float | None] = mapped_column(Float)
    ev_to_fcf_fy: Mapped[float | None] = mapped_column(Float)

    # --- management effectiveness ---
    roe_fy: Mapped[float | None] = mapped_column(Float)
    roe_ttm: Mapped[float | None] = mapped_column(Float)
    roe_5y_avg: Mapped[float | None] = mapped_column(Float)
    roa_fy: Mapped[float | None] = mapped_column(Float)
    roa_5y_avg: Mapped[float | None] = mapped_column(Float)
    roi_fy: Mapped[float | None] = mapped_column(Float)
    roi_5y_avg: Mapped[float | None] = mapped_column(Float)
    asset_turnover_fy: Mapped[float | None] = mapped_column(Float)
    inventory_turnover_fy: Mapped[float | None] = mapped_column(Float)
    receivables_turnover_fy: Mapped[float | None] = mapped_column(Float)

    # --- margins ---
    gross_margin_ttm: Mapped[float | None] = mapped_column(Float)
    gross_margin_5y_avg: Mapped[float | None] = mapped_column(Float)
    operating_margin_ttm: Mapped[float | None] = mapped_column(Float)
    operating_margin_5y_avg: Mapped[float | None] = mapped_column(Float)
    net_margin_ttm: Mapped[float | None] = mapped_column(Float)
    net_margin_5y_avg: Mapped[float | None] = mapped_column(Float)
    pretax_margin_ttm: Mapped[float | None] = mapped_column(Float)
    fcf_per_revenue_5y_avg: Mapped[float | None] = mapped_column(Float)

    # --- financial strength ---
    debt_to_equity_fy: Mapped[float | None] = mapped_column(Float)
    debt_to_equity_q: Mapped[float | None] = mapped_column(Float)
    lt_debt_to_equity_fy: Mapped[float | None] = mapped_column(Float)
    current_ratio_fy: Mapped[float | None] = mapped_column(Float)
    quick_ratio_fy: Mapped[float | None] = mapped_column(Float)
    interest_coverage_ttm: Mapped[float | None] = mapped_column(Float)
    interest_coverage_fy: Mapped[float | None] = mapped_column(Float)
    payout_ratio_ttm: Mapped[float | None] = mapped_column(Float)
    net_debt_fy: Mapped[float | None] = mapped_column(Float)
    fcf_fy: Mapped[float | None] = mapped_column(Float)

    # --- growth ---
    eps_growth_ttm: Mapped[float | None] = mapped_column(Float)
    eps_cagr_3y: Mapped[float | None] = mapped_column(Float)
    eps_cagr_5y: Mapped[float | None] = mapped_column(Float)
    eps_growth_q_yoy: Mapped[float | None] = mapped_column(Float)
    revenue_growth_ttm: Mapped[float | None] = mapped_column(Float)
    revenue_cagr_3y: Mapped[float | None] = mapped_column(Float)
    revenue_cagr_5y: Mapped[float | None] = mapped_column(Float)
    revenue_growth_q_yoy: Mapped[float | None] = mapped_column(Float)
    bvps_growth_5y: Mapped[float | None] = mapped_column(Float)
    ebitda_cagr_5y: Mapped[float | None] = mapped_column(Float)
    fcf_cagr_5y: Mapped[float | None] = mapped_column(Float)
    net_margin_growth_5y: Mapped[float | None] = mapped_column(Float)

    # --- per share ---
    eps_ttm: Mapped[float | None] = mapped_column(Float)
    eps_fy: Mapped[float | None] = mapped_column(Float)
    eps_normalized_fy: Mapped[float | None] = mapped_column(Float)
    bvps_fy: Mapped[float | None] = mapped_column(Float)
    dps_ttm: Mapped[float | None] = mapped_column(Float)
    cfps_ttm: Mapped[float | None] = mapped_column(Float)
    revenue_ps_ttm: Mapped[float | None] = mapped_column(Float)
    cash_ps_fy: Mapped[float | None] = mapped_column(Float)

    # --- income statement (absolute, INR lakh as returned) ---
    revenue_ttm: Mapped[float | None] = mapped_column(Float)
    revenue_fy: Mapped[float | None] = mapped_column(Float)
    net_income_ttm: Mapped[float | None] = mapped_column(Float)
    net_income_fy: Mapped[float | None] = mapped_column(Float)
    ebitda_ttm: Mapped[float | None] = mapped_column(Float)
    ebitda_fy: Mapped[float | None] = mapped_column(Float)
    ebt_ttm: Mapped[float | None] = mapped_column(Float)

    # --- price & volume (vendor's view; Groww bars remain source of truth) ---
    market_cap: Mapped[float | None] = mapped_column(Float)
    beta: Mapped[float | None] = mapped_column(Float)
    week52_high: Mapped[float | None] = mapped_column(Float)
    week52_low: Mapped[float | None] = mapped_column(Float)
    avg_volume_10d: Mapped[float | None] = mapped_column(Float)
    avg_volume_3m: Mapped[float | None] = mapped_column(Float)
    rel_perf_13w: Mapped[float | None] = mapped_column(Float)
    rel_perf_26w: Mapped[float | None] = mapped_column(Float)
    rel_perf_52w: Mapped[float | None] = mapped_column(Float)
    rel_perf_ytd: Mapped[float | None] = mapped_column(Float)

    # --- analyst consensus (counts by rating, latest vs history) ---
    analyst_rating_mean: Mapped[float | None] = mapped_column(Float)
    analyst_count: Mapped[float | None] = mapped_column(Float)
    analyst_rating_mean_1m_ago: Mapped[float | None] = mapped_column(Float)
    analyst_rating_mean_3m_ago: Mapped[float | None] = mapped_column(Float)

    risk_std_dev: Mapped[float | None] = mapped_column(Float)
    risk_category: Mapped[str | None] = mapped_column(String(60))

    raw: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class FinancialStatement(Base, TimestampMixin):
    """Income statement / balance sheet / cash flow line items.

    `/stock` returns 8 annual and 11 interim periods with 28 + 41 + 18 lines
    each, which is what makes a full 9-test Piotroski score and real accrual
    and cash-conversion factors possible.
    """

    __tablename__ = "financial_statements"
    __table_args__ = (
        UniqueConstraint("symbol", "fiscal_end", "period_type", "statement", "line_key"),
        Index("ix_financial_statements_lookup", "symbol", "statement", "period_type", "fiscal_end"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        ForeignKey("instruments.symbol", ondelete="CASCADE"), nullable=False
    )
    fiscal_end: Mapped[date] = mapped_column(Date, nullable=False)
    fiscal_year: Mapped[str | None] = mapped_column(String(8))
    period_type: Mapped[str] = mapped_column(String(10), nullable=False)  # Annual | Interim
    statement: Mapped[str] = mapped_column(String(4), nullable=False)  # INC | BAL | CAS
    line_key: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    value: Mapped[float | None] = mapped_column(Float)

    known_on: Mapped[date] = mapped_column(Date, nullable=False)
    known_on_estimated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Estimate(Base, TimestampMixin):
    """Analyst actuals and estimates from `/stock_forecasts`.

    `actual_report_date` is the real earnings announcement timestamp and is the
    primary source for `known_on` everywhere else. `sue` (standardised
    unexpected earnings) drives the post-earnings-announcement-drift factor.
    """

    __tablename__ = "estimates"
    __table_args__ = (
        UniqueConstraint("symbol", "measure", "period_type", "fiscal_year", "fiscal_month"),
        Index("ix_estimates_symbol_measure", "symbol", "measure"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        ForeignKey("instruments.symbol", ondelete="CASCADE"), nullable=False
    )
    measure: Mapped[str] = mapped_column(String(8), nullable=False)  # EPS, SAL, ROE, ...
    period_type: Mapped[str] = mapped_column(String(10), nullable=False)  # Annual | Interim
    fiscal_year: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fiscal_month: Mapped[int | None] = mapped_column(BigInteger)
    relative_period: Mapped[int | None] = mapped_column(BigInteger)
    # The calendar date the fiscal period actually ends. Stored explicitly
    # because the vendor labels interim periods by Indian fiscal year -- Q1 of
    # "FY2027" is the quarter ending June *2026* -- so deriving it from
    # fiscal_year is off by a year for three quarters out of four.
    period_end: Mapped[date | None] = mapped_column(Date, index=True)

    actual: Mapped[float | None] = mapped_column(Float)
    mean_estimate: Mapped[float | None] = mapped_column(Float)
    high_estimate: Mapped[float | None] = mapped_column(Float)
    low_estimate: Mapped[float | None] = mapped_column(Float)
    num_estimates: Mapped[float | None] = mapped_column(Float)
    std_dev: Mapped[float | None] = mapped_column(Float)

    surprise_pct: Mapped[float | None] = mapped_column(Float)
    surprise_mean: Mapped[float | None] = mapped_column(Float)
    sue: Mapped[float | None] = mapped_column(Float)

    actual_report_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class PriceTarget(Base, TimestampMixin):
    __tablename__ = "price_targets"
    __table_args__ = (UniqueConstraint("symbol", "as_of"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        ForeignKey("instruments.symbol", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    mean: Mapped[float | None] = mapped_column(Float)
    median: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    std_dev: Mapped[float | None] = mapped_column(Float)
    num_estimates: Mapped[float | None] = mapped_column(Float)


class ValuationHistory(Base):
    """Multi-year valuation multiples from `/historical_data`.

    Enables "cheap relative to its own history" factors, which plain
    cross-sectional value screens miss entirely.
    """

    __tablename__ = "valuation_history"
    __table_args__ = (UniqueConstraint("symbol", "date", "metric"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        ForeignKey("instruments.symbol", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    metric: Mapped[str] = mapped_column(String(20), nullable=False)  # pe | ptb | evebitda | mcs
    value: Mapped[float | None] = mapped_column(Float)


class Shareholding(Base):
    __tablename__ = "shareholding"
    __table_args__ = (UniqueConstraint("symbol", "holding_date", "category"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        ForeignKey("instruments.symbol", ondelete="CASCADE"), nullable=False
    )
    holding_date: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)  # Promoter | FII | MF | Other
    percentage: Mapped[float | None] = mapped_column(Float)


class CorporateAction(Base, TimestampMixin):
    __tablename__ = "corporate_actions"
    __table_args__ = (
        UniqueConstraint("symbol", "action_type", "ex_date", "value"),
        Index("ix_corporate_actions_symbol_ex", "symbol", "ex_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        ForeignKey("instruments.symbol", ondelete="CASCADE"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(30), nullable=False)  # dividend|bonus|split|...
    ex_date: Mapped[date | None] = mapped_column(Date)
    record_date: Mapped[date | None] = mapped_column(Date)
    announced_date: Mapped[date | None] = mapped_column(Date)
    value: Mapped[float | None] = mapped_column(Float)
    percentage: Mapped[float | None] = mapped_column(Float)
    interim_or_final: Mapped[str | None] = mapped_column(String(20))
    remarks: Mapped[str | None] = mapped_column(Text)


class Announcement(Base, TimestampMixin):
    __tablename__ = "announcements"
    __table_args__ = (
        UniqueConstraint("symbol", "published_at", "headline"),
        Index("ix_announcements_symbol_published", "symbol", "published_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        ForeignKey("instruments.symbol", ondelete="CASCADE"), nullable=False
    )
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
