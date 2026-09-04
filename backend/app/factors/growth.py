"""Growth factors."""

from __future__ import annotations

import pandas as pd

from app.factors.panel import Panel, statement_latest
from app.factors.registry import register
from app.factors.stats import safe_divide


def _col(panel: Panel, name: str) -> pd.Series:
    if panel.fundamentals.empty or name not in panel.fundamentals.columns:
        return pd.Series(dtype=float, index=pd.Index(panel.symbols, name="symbol"))
    return pd.to_numeric(panel.fundamentals[name], errors="coerce")


@register(
    "revenue_growth_5y",
    "Revenue growth (5y)",
    "growth",
    "Five-year compound annual revenue growth.",
    unit="%",
)
def revenue_growth_5y(panel: Panel) -> pd.Series:
    return _col(panel, "revenue_cagr_5y")


@register(
    "eps_growth_5y",
    "Earnings growth (5y)",
    "growth",
    "Five-year compound annual earnings-per-share growth.",
    unit="%",
)
def eps_growth_5y(panel: Panel) -> pd.Series:
    return _col(panel, "eps_cagr_5y")


@register(
    "revenue_growth_ttm",
    "Revenue growth (TTM)",
    "growth",
    "Trailing twelve-month revenue against the prior twelve months.",
    unit="%",
)
def revenue_growth_ttm(panel: Panel) -> pd.Series:
    return _col(panel, "revenue_growth_ttm")


@register(
    "eps_growth_ttm",
    "Earnings growth (TTM)",
    "growth",
    "Trailing twelve-month earnings against the prior twelve months.",
    unit="%",
)
def eps_growth_ttm(panel: Panel) -> pd.Series:
    return _col(panel, "eps_growth_ttm")


@register(
    "growth_acceleration",
    "Growth acceleration",
    "growth",
    "Latest quarterly revenue growth against the five-year trend. Positive means "
    "growth is speeding up, which tends to matter more than its level.",
    unit="pp",
)
def growth_acceleration(panel: Panel) -> pd.Series:
    return _col(panel, "revenue_growth_q_yoy") - _col(panel, "revenue_cagr_5y")


@register(
    "book_value_growth",
    "Book value growth",
    "growth",
    "Five-year growth in book value per share -- compounding that has actually "
    "reached the balance sheet.",
    unit="%",
)
def book_value_growth(panel: Panel) -> pd.Series:
    return _col(panel, "bvps_growth_5y")


@register(
    "reinvestment_rate",
    "Reinvestment rate",
    "growth",
    "Retained earnings as a share of profit, multiplied by return on equity: the "
    "rate at which the business can fund its own growth.",
    unit="%",
)
def reinvestment_rate(panel: Panel) -> pd.Series:
    payout = _col(panel, "payout_ratio_ttm").clip(0, 100)
    retention = (100.0 - payout) / 100.0
    return retention * _col(panel, "roe_ttm").fillna(_col(panel, "roe_fy"))


@register(
    "profit_growth_3y",
    "Profit growth (3y)",
    "growth",
    "Three-year growth in net profit, computed from the statements rather than a vendor ratio.",
    unit="%",
)
def profit_growth_3y(panel: Panel) -> pd.Series:
    latest = statement_latest(panel, "INC", "NetIncome", "Annual", 0)
    prior = statement_latest(panel, "INC", "NetIncome", "Annual", 3)
    # Growth from a loss-making base is not meaningful.
    prior = prior.where(prior > 0)
    return (safe_divide(latest, prior) ** (1 / 3) - 1.0) * 100.0
