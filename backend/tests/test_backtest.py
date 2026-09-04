"""Backtest correctness.

The decisive tests here are about leakage, not returns: a backtest that sees
tomorrow's earnings produces beautiful numbers and teaches nothing.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backtest.costs import DEFAULT_COSTS, ZERO_COSTS
from app.backtest.engine import rebalance_dates
from app.backtest.metrics import compute_metrics, max_drawdown
from app.db.models.fundamentals import FinancialStatement
from app.factors.panel import build_panel


def test_rebalance_dates_respect_frequency() -> None:
    start, end = dt.date(2024, 1, 15), dt.date(2024, 12, 31)
    assert len(rebalance_dates(start, end, "monthly")) == 12
    assert len(rebalance_dates(start, end, "quarterly")) == 4
    assert len(rebalance_dates(start, end, "yearly")) == 1


def test_rebalance_dates_never_exceed_the_end() -> None:
    days = rebalance_dates(dt.date(2024, 1, 1), dt.date(2024, 6, 30), "quarterly")
    assert all(d <= dt.date(2024, 6, 30) for d in days)
    assert days[0] >= dt.date(2024, 1, 1)


def test_costs_are_asymmetric_and_material() -> None:
    """Stamp duty is buy-side only, so a buy must cost more than a sell of the
    same value -- and the round trip has to be big enough to matter."""
    assert DEFAULT_COSTS.cost(100_000, "BUY") > DEFAULT_COSTS.cost(100_000, "SELL")
    assert 0.2 < DEFAULT_COSTS.round_trip_pct() < 1.0
    assert ZERO_COSTS.cost(100_000, "BUY") == 0.0


def test_costs_scale_linearly() -> None:
    assert DEFAULT_COSTS.cost(200_000, "BUY") == pytest.approx(
        2 * DEFAULT_COSTS.cost(100_000, "BUY")
    )


def test_max_drawdown_measures_peak_to_trough() -> None:
    curve = pd.Series([100.0, 120.0, 60.0, 90.0])
    assert max_drawdown(curve) == pytest.approx(-0.5)


def test_metrics_on_a_flat_curve_are_not_nonsense() -> None:
    idx = pd.date_range("2024-01-01", periods=300, freq="D")
    m = compute_metrics(pd.Series(1.0, index=idx))
    assert m["cagr_pct"] == pytest.approx(0.0, abs=0.01)
    assert m["max_drawdown_pct"] == pytest.approx(0.0)


def test_metrics_recover_a_known_growth_rate() -> None:
    idx = pd.date_range("2020-01-01", "2024-01-01", freq="D")
    # Exactly 10% a year, compounded daily.
    curve = pd.Series((1.10 ** (pd.Series(range(len(idx))) / 365.25)).to_numpy(), index=idx)
    m = compute_metrics(curve)
    assert m["cagr_pct"] == pytest.approx(10.0, abs=0.3)


# --- the important one -----------------------------------------------------


def test_panel_never_includes_fundamentals_the_market_could_not_have_known(
    db: Session,
) -> None:
    """The core point-in-time guarantee.

    Uses whatever real data is loaded; skips when the database is empty so the
    suite still runs on a fresh checkout.
    """
    loaded = db.scalar(select(func.count()).select_from(FinancialStatement)) or 0
    if loaded == 0:
        pytest.skip("no statement data loaded")

    symbols = list(db.scalars(select(FinancialStatement.symbol).distinct().limit(15)).all())
    as_of = dt.date(2024, 6, 1)
    panel = build_panel(db, symbols, as_of)

    if panel.statements.empty:
        pytest.skip("no statements known by the test date")

    # Every row in the panel must have been knowable on the as-of date.
    known = pd.to_datetime(
        db.execute(
            select(FinancialStatement.known_on).where(
                FinancialStatement.symbol.in_(symbols),
                FinancialStatement.known_on <= as_of,
            )
        )
        .scalars()
        .all()
    )
    assert len(known) == len(panel.statements)

    # And the panel must be strictly smaller than the unfiltered table, or the
    # filter is not doing anything and the test is vacuous.
    total = db.scalar(
        select(func.count())
        .select_from(FinancialStatement)
        .where(FinancialStatement.symbol.in_(symbols))
    )
    assert total is not None and len(panel.statements) < total


def test_estimates_are_gated_on_the_announcement_date(db: Session) -> None:
    """Post-earnings-drift factors must not see a result before it was
    announced -- that is the one thing that would make them look magical."""
    from app.db.models.fundamentals import Estimate

    loaded = db.scalar(select(func.count()).select_from(Estimate)) or 0
    if loaded == 0:
        pytest.skip("no estimate data loaded")

    symbols = list(db.scalars(select(Estimate.symbol).distinct().limit(15)).all())
    as_of = dt.date(2024, 6, 1)
    panel = build_panel(db, symbols, as_of)
    if panel.estimates.empty:
        pytest.skip("no estimates known by the test date")

    reported = pd.to_datetime(panel.estimates["actual_report_date"], utc=True).dt.date
    assert (reported <= as_of).all()


def test_a_later_panel_knows_at_least_as_much_as_an_earlier_one(db: Session) -> None:
    """Knowledge only accumulates; a later as-of date can never see less."""
    loaded = db.scalar(select(func.count()).select_from(FinancialStatement)) or 0
    if loaded == 0:
        pytest.skip("no statement data loaded")
    symbols = list(db.scalars(select(FinancialStatement.symbol).distinct().limit(10)).all())
    early = build_panel(db, symbols, dt.date(2023, 1, 1))
    late = build_panel(db, symbols, dt.date(2025, 1, 1))
    assert len(late.statements) >= len(early.statements)
