"""Building the point-in-time panel a factor computation runs against.

One function serves both the nightly precompute and the backtester, which is
what guarantees a backtest sees exactly what the screener would have seen on
that date. Every fundamental read is filtered by ``known_on <= as_of``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.models.fundamentals import (
    Estimate,
    FinancialStatement,
    FundamentalSnapshot,
    PriceTarget,
    Shareholding,
)
from app.db.models.market import DailyBar, Instrument

BENCHMARK_SYMBOL = "NIFTY"


@dataclass
class Panel:
    """Everything the factor library needs for one as-of date."""

    as_of: dt.date
    symbols: list[str]
    sectors: pd.Series
    names: pd.Series
    prices: pd.DataFrame  # index=date, columns=symbol (close)
    volumes: pd.DataFrame
    highs: pd.DataFrame
    lows: pd.DataFrame
    benchmark: pd.Series
    fundamentals: pd.DataFrame  # index=symbol
    statements: pd.DataFrame  # long form: symbol, fiscal_end, statement, line_key, value
    estimates: pd.DataFrame
    targets: pd.DataFrame
    shareholding: pd.DataFrame
    meta: dict[str, object] = field(default_factory=dict)

    @property
    def latest_close(self) -> pd.Series:
        if self.prices.empty:
            return pd.Series(dtype=float)
        return self.prices.ffill().iloc[-1]


def _latest_known_snapshot(as_of: dt.date, symbols: list[str]) -> Select:
    """The most recent snapshot per symbol that was *knowable* by as_of.

    DISTINCT ON is the cheap way to do this in Postgres: one index scan rather
    than a self-join or a window function over the whole table.
    """
    return (
        select(FundamentalSnapshot)
        .where(
            FundamentalSnapshot.symbol.in_(symbols),
            FundamentalSnapshot.known_on <= as_of,
        )
        .distinct(FundamentalSnapshot.symbol)
        .order_by(
            FundamentalSnapshot.symbol,
            FundamentalSnapshot.known_on.desc(),
            FundamentalSnapshot.snapshot_date.desc(),
        )
    )


def build_panel(
    db: Session,
    symbols: list[str],
    as_of: dt.date | None = None,
    *,
    price_lookback_days: int = 800,
    with_statements: bool = True,
) -> Panel:
    as_of = as_of or dt.date.today()
    symbols = sorted(set(symbols))
    price_start = as_of - dt.timedelta(days=price_lookback_days)

    instruments = db.execute(
        select(Instrument.symbol, Instrument.name, Instrument.sector).where(
            Instrument.symbol.in_(symbols)
        )
    ).all()
    sectors = pd.Series(
        {s: (sec or "Unknown") for s, _n, sec in instruments}, dtype=object
    ).reindex(symbols)
    names = pd.Series({s: n for s, n, _sec in instruments}, dtype=object).reindex(symbols)

    bar_rows = db.execute(
        select(
            DailyBar.symbol,
            DailyBar.date,
            DailyBar.close,
            DailyBar.volume,
            DailyBar.high,
            DailyBar.low,
        )
        .where(
            DailyBar.symbol.in_([*symbols, BENCHMARK_SYMBOL]),
            DailyBar.date > price_start,
            DailyBar.date <= as_of,
        )
        .order_by(DailyBar.date)
    ).all()

    bars = pd.DataFrame(bar_rows, columns=["symbol", "date", "close", "volume", "high", "low"])
    if bars.empty:
        empty = pd.DataFrame()
        prices = volumes = highs = lows = empty
        benchmark = pd.Series(dtype=float)
    else:
        bars["date"] = pd.to_datetime(bars["date"])
        pivot = bars.pivot_table(
            index="date", columns="symbol", values=["close", "volume", "high", "low"]
        )
        prices = pivot["close"]
        volumes = pivot["volume"]
        highs = pivot["high"]
        lows = pivot["low"]
        benchmark = (
            prices[BENCHMARK_SYMBOL].copy()
            if BENCHMARK_SYMBOL in prices.columns
            else pd.Series(dtype=float)
        )
        for frame in (prices, volumes, highs, lows):
            if BENCHMARK_SYMBOL in frame.columns and BENCHMARK_SYMBOL not in symbols:
                frame.drop(columns=[BENCHMARK_SYMBOL], inplace=True)

    snapshots = db.scalars(_latest_known_snapshot(as_of, symbols)).all()
    fundamentals = _snapshots_to_frame(snapshots, symbols)

    statements = pd.DataFrame(
        columns=["symbol", "fiscal_end", "period_type", "statement", "line_key", "value"]
    )
    if with_statements:
        stmt_rows = db.execute(
            select(
                FinancialStatement.symbol,
                FinancialStatement.fiscal_end,
                FinancialStatement.period_type,
                FinancialStatement.statement,
                FinancialStatement.line_key,
                FinancialStatement.value,
            ).where(
                FinancialStatement.symbol.in_(symbols),
                FinancialStatement.known_on <= as_of,
            )
        ).all()
        if stmt_rows:
            statements = pd.DataFrame(stmt_rows, columns=list(statements.columns))

    est_rows = db.execute(
        select(
            Estimate.symbol,
            Estimate.measure,
            Estimate.period_type,
            Estimate.period_end,
            Estimate.actual,
            Estimate.mean_estimate,
            Estimate.surprise_pct,
            Estimate.sue,
            Estimate.actual_report_date,
        ).where(
            Estimate.symbol.in_(symbols),
            Estimate.actual_report_date.is_not(None),
            func.date(Estimate.actual_report_date) <= as_of,
        )
    ).all()
    estimates = pd.DataFrame(
        est_rows,
        columns=[
            "symbol",
            "measure",
            "period_type",
            "period_end",
            "actual",
            "mean_estimate",
            "surprise_pct",
            "sue",
            "actual_report_date",
        ],
    )

    target_rows = db.execute(
        select(PriceTarget.symbol, PriceTarget.as_of, PriceTarget.mean, PriceTarget.num_estimates)
        .where(PriceTarget.symbol.in_(symbols), PriceTarget.as_of <= as_of)
        .distinct(PriceTarget.symbol)
        .order_by(PriceTarget.symbol, PriceTarget.as_of.desc())
    ).all()
    targets = pd.DataFrame(target_rows, columns=["symbol", "as_of", "mean", "num_estimates"])

    share_rows = db.execute(
        select(
            Shareholding.symbol,
            Shareholding.holding_date,
            Shareholding.category,
            Shareholding.percentage,
        ).where(
            Shareholding.symbol.in_(symbols),
            # Shareholding patterns are filed ~45 days after quarter end.
            Shareholding.holding_date <= as_of - dt.timedelta(days=45),
        )
    ).all()
    shareholding = pd.DataFrame(
        share_rows, columns=["symbol", "holding_date", "category", "percentage"]
    )

    return Panel(
        as_of=as_of,
        symbols=symbols,
        sectors=sectors,
        names=names,
        prices=prices,
        volumes=volumes,
        highs=highs,
        lows=lows,
        benchmark=benchmark,
        fundamentals=fundamentals,
        statements=statements,
        estimates=estimates,
        targets=targets,
        shareholding=shareholding,
    )


_SNAPSHOT_SKIP = {"id", "symbol", "snapshot_date", "raw", "created_at", "updated_at"}


def _snapshots_to_frame(
    snapshots: Sequence[FundamentalSnapshot], symbols: list[str]
) -> pd.DataFrame:
    columns = [
        c.name for c in FundamentalSnapshot.__table__.columns if c.name not in _SNAPSHOT_SKIP
    ]
    if not snapshots:
        return pd.DataFrame(index=pd.Index(symbols, name="symbol"), columns=columns, dtype=float)
    records = {s.symbol: {c: getattr(s, c) for c in columns} for s in snapshots}
    frame = pd.DataFrame.from_dict(records, orient="index")
    frame.index.name = "symbol"
    return frame.reindex(symbols)


def statement_series(
    panel: Panel, statement: str, line_key: str, period_type: str = "Annual"
) -> pd.DataFrame:
    """Wide frame of one statement line: index=symbol, columns=fiscal_end.

    Sorted most-recent-first so ``.iloc[:, 0]`` is the latest known period and
    ``.iloc[:, 1]`` the one before -- which is what the year-on-year tests in
    Piotroski and the accrual factors need.
    """
    df = panel.statements
    if df.empty:
        return pd.DataFrame()
    mask = (df["statement"] == statement) & (df["line_key"] == line_key)
    if period_type:
        mask &= df["period_type"] == period_type
    subset = df[mask]
    if subset.empty:
        return pd.DataFrame()
    wide = subset.pivot_table(index="symbol", columns="fiscal_end", values="value", aggfunc="last")
    return wide.reindex(sorted(wide.columns, reverse=True), axis=1)


def statement_latest(
    panel: Panel, statement: str, line_key: str, period_type: str = "Annual", offset: int = 0
) -> pd.Series:
    """One statement line at ``offset`` periods back, *per symbol*.

    Ranked within each symbol rather than taken from a shared column position.
    Companies do not share a fiscal calendar -- most Indian annuals end 31
    March but plenty end in December -- so a pivoted frame's first column is
    only the latest period for the subset of symbols that happen to use it, and
    everyone else reads NaN. That silently emptied every factor built on
    year-on-year statement comparisons.
    """
    empty = pd.Series(dtype=float, index=pd.Index(panel.symbols, name="symbol"))
    df = panel.statements
    if df.empty:
        return empty

    mask = (df["statement"] == statement) & (df["line_key"] == line_key)
    if period_type:
        mask &= df["period_type"] == period_type
    subset = df[mask].dropna(subset=["value"])
    if subset.empty:
        return empty

    ordered = subset.sort_values(["symbol", "fiscal_end"], ascending=[True, False])
    ordered = ordered.drop_duplicates(subset=["symbol", "fiscal_end"], keep="first")
    nth = ordered.groupby("symbol", sort=False).nth(offset)
    if nth.empty:
        return empty
    return nth.set_index("symbol")["value"].astype(float).reindex(panel.symbols)


__all__ = [
    "BENCHMARK_SYMBOL",
    "Panel",
    "build_panel",
    "statement_latest",
    "statement_series",
]
