"""Price and volume factors.

These are computed from the daily bars rather than the vendor's precomputed
percentage changes, so the whole family is available at any historical as-of
date for the backtester.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.factors.panel import Panel
from app.factors.registry import register

TRADING_DAYS_YEAR = 252
SKIP_MONTH = 21


def _returns(panel: Panel, lookback: int, skip: int = 0) -> pd.Series:
    prices = panel.prices
    if prices.empty or len(prices) < lookback + skip + 1:
        return pd.Series(dtype=float, index=pd.Index(panel.symbols, name="symbol"))
    filled = prices.ffill()
    end = filled.iloc[-1 - skip]
    start = filled.iloc[-1 - skip - lookback]
    return ((end / start.replace(0.0, np.nan)) - 1.0).reindex(panel.symbols) * 100.0


@register(
    "momentum_12_1",
    "Momentum (12-1)",
    "momentum",
    "Twelve-month price return excluding the most recent month. Skipping the last "
    "month avoids the well-documented short-term reversal that otherwise works "
    "against the momentum signal.",
    sector_neutral=False,
    unit="%",
)
def momentum_12_1(panel: Panel) -> pd.Series:
    return _returns(panel, TRADING_DAYS_YEAR - SKIP_MONTH, SKIP_MONTH)


@register(
    "momentum_6_1",
    "Momentum (6-1)",
    "momentum",
    "Six-month price return excluding the most recent month.",
    sector_neutral=False,
    unit="%",
)
def momentum_6_1(panel: Panel) -> pd.Series:
    return _returns(panel, 126 - SKIP_MONTH, SKIP_MONTH)


@register(
    "momentum_3m",
    "Momentum (3m)",
    "momentum",
    "Three-month price return.",
    sector_neutral=False,
    unit="%",
)
def momentum_3m(panel: Panel) -> pd.Series:
    return _returns(panel, 63)


@register(
    "risk_adjusted_momentum",
    "Risk-adjusted momentum",
    "momentum",
    "Twelve-month-minus-one-month return divided by annualised volatility, so a "
    "steady climb outranks the same return delivered by one violent gap.",
    sector_neutral=False,
    unit="x",
)
def risk_adjusted_momentum(panel: Panel) -> pd.Series:
    mom = momentum_12_1(panel)
    prices = panel.prices
    if prices.empty:
        return mom
    daily = prices.ffill().pct_change(fill_method=None)
    vol = daily.tail(TRADING_DAYS_YEAR).std(ddof=0) * np.sqrt(TRADING_DAYS_YEAR) * 100.0
    return (mom / vol.replace(0.0, np.nan)).reindex(panel.symbols)


@register(
    "near_52w_high",
    "Proximity to 52-week high",
    "momentum",
    "Current price as a percentage of the 52-week high. Names pressing against "
    "their highs tend to keep going, and this is the cleanest way to express it.",
    sector_neutral=False,
    unit="%",
)
def near_52w_high(panel: Panel) -> pd.Series:
    prices = panel.prices
    if prices.empty:
        return pd.Series(dtype=float, index=pd.Index(panel.symbols, name="symbol"))
    window = prices.ffill().tail(TRADING_DAYS_YEAR)
    high = window.max()
    return (window.iloc[-1] / high.replace(0.0, np.nan) * 100.0).reindex(panel.symbols)


@register(
    "trend_strength",
    "Trend strength",
    "momentum",
    "How far price sits above its own 200-day moving average.",
    sector_neutral=False,
    unit="%",
)
def trend_strength(panel: Panel) -> pd.Series:
    prices = panel.prices
    if prices.empty or len(prices) < 200:
        return pd.Series(dtype=float, index=pd.Index(panel.symbols, name="symbol"))
    filled = prices.ffill()
    sma = filled.tail(200).mean()
    return ((filled.iloc[-1] / sma.replace(0.0, np.nan)) - 1.0).reindex(panel.symbols) * 100.0


@register(
    "relative_strength",
    "Relative strength vs Nifty",
    "momentum",
    "Twelve-month return in excess of the index, isolating stock-specific strength "
    "from a rising market.",
    sector_neutral=False,
    unit="pp",
)
def relative_strength(panel: Panel) -> pd.Series:
    stock = _returns(panel, TRADING_DAYS_YEAR)
    bench = panel.benchmark
    if bench.empty or len(bench) < TRADING_DAYS_YEAR + 1:
        return stock
    filled = bench.ffill()
    bench_return = (filled.iloc[-1] / filled.iloc[-1 - TRADING_DAYS_YEAR] - 1.0) * 100.0
    return stock - float(bench_return)


@register(
    "volume_surge",
    "Volume surge",
    "momentum",
    "Ten-day average volume against the three-month average. Sustained heavy "
    "turnover marks names institutions are actually moving through.",
    sector_neutral=False,
    unit="x",
)
def volume_surge(panel: Panel) -> pd.Series:
    volumes = panel.volumes
    if volumes.empty or len(volumes) < 63:
        return pd.Series(dtype=float, index=pd.Index(panel.symbols, name="symbol"))
    recent = volumes.tail(10).mean()
    baseline = volumes.tail(63).mean().replace(0.0, np.nan)
    return (recent / baseline).reindex(panel.symbols)
