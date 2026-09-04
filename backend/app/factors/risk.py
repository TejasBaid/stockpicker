"""Risk factors. All are inverted so that a higher score means lower risk."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.factors.panel import Panel
from app.factors.registry import register

TRADING_DAYS_YEAR = 252


def _daily_returns(panel: Panel) -> pd.DataFrame:
    if panel.prices.empty:
        return pd.DataFrame()
    return panel.prices.ffill().pct_change(fill_method=None).tail(TRADING_DAYS_YEAR)


@register(
    "low_volatility",
    "Low volatility",
    "risk",
    "Annualised volatility of daily returns, inverted. Low-volatility names have "
    "historically delivered better risk-adjusted returns than their beta implies.",
    higher_is_better=False,
    sector_neutral=False,
    unit="%",
)
def low_volatility(panel: Panel) -> pd.Series:
    returns = _daily_returns(panel)
    if returns.empty:
        return pd.Series(dtype=float, index=pd.Index(panel.symbols, name="symbol"))
    return (returns.std(ddof=0) * np.sqrt(TRADING_DAYS_YEAR) * 100.0).reindex(panel.symbols)


@register(
    "low_beta",
    "Low beta",
    "risk",
    "Sensitivity to the index over the past year, inverted.",
    higher_is_better=False,
    sector_neutral=False,
    unit="x",
)
def low_beta(panel: Panel) -> pd.Series:
    returns = _daily_returns(panel)
    bench = panel.benchmark
    index = pd.Index(panel.symbols, name="symbol")
    if returns.empty or bench.empty:
        return pd.Series(dtype=float, index=index)

    bench_returns = bench.ffill().pct_change(fill_method=None).tail(TRADING_DAYS_YEAR)
    aligned = returns.join(bench_returns.rename("_bench"), how="inner").dropna(subset=["_bench"])
    if len(aligned) < 60:
        return pd.Series(dtype=float, index=index)

    market = aligned.pop("_bench")
    market_var = market.var(ddof=0)
    if not market_var or not np.isfinite(market_var):
        return pd.Series(dtype=float, index=index)
    return (aligned.apply(lambda col: col.cov(market)) / market_var).reindex(index)


@register(
    "low_drawdown",
    "Shallow drawdown",
    "risk",
    "Worst peak-to-trough fall over the past year, inverted. Captures tail risk "
    "that volatility alone misses.",
    higher_is_better=False,
    sector_neutral=False,
    unit="%",
)
def low_drawdown(panel: Panel) -> pd.Series:
    prices = panel.prices
    if prices.empty:
        return pd.Series(dtype=float, index=pd.Index(panel.symbols, name="symbol"))
    window = prices.ffill().tail(TRADING_DAYS_YEAR)
    drawdown = window / window.cummax() - 1.0
    return (drawdown.min() * 100.0).abs().reindex(panel.symbols)


@register(
    "liquidity",
    "Liquidity",
    "risk",
    "Average daily traded value over the past month, in crore. Determines whether "
    "a position can actually be built and exited.",
    sector_neutral=False,
    unit="Cr",
)
def liquidity(panel: Panel) -> pd.Series:
    prices, volumes = panel.prices, panel.volumes
    if prices.empty or volumes.empty:
        return pd.Series(dtype=float, index=pd.Index(panel.symbols, name="symbol"))
    traded_value = (prices.ffill() * volumes.fillna(0.0)).tail(21).mean()
    return (traded_value / 1e7).reindex(panel.symbols)
