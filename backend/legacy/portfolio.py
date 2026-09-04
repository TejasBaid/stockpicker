"""Portfolio construction: gating, diversified selection, risk-based sizing."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config, factors


def apply_gates(
    scores: pd.DataFrame,
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    min_liquidity_cr: float,
    require_uptrend: bool,
) -> pd.DataFrame:
    """Drop stocks that fail liquidity / trend qualifiers before ranking.

    Without this, a factor screen can happily rank an illiquid microcap or a
    stock in a structural downtrend at #1 purely because it looks statistically
    cheap or "low vol" (low vol is often just no one trading it).
    """
    stock_prices = prices.drop(columns=[config.INDEX_TICKER], errors="ignore")
    out = scores.copy()

    liq = factors.liquidity_value_cr(stock_prices, volumes)
    out["liquidity_cr"] = liq.reindex(out.index)
    out = out[out["liquidity_cr"].fillna(0) >= min_liquidity_cr]

    if require_uptrend:
        uptrend = factors.trend_qualifier(stock_prices)
        out["above_200sma"] = uptrend.reindex(out.index)
        out = out[out["above_200sma"].fillna(False)]

    return out


def diversified_selection(
    ranked: pd.DataFrame,
    prices: pd.DataFrame,
    top_n: int,
    max_per_sector: int,
    max_pair_corr: float,
    fundamentals: pd.DataFrame,
) -> list[str]:
    """Greedy selection off the ranked composite score, skipping candidates
    that would breach a sector cap or that are too highly correlated with an
    already-selected name (redundant risk, not real diversification).
    """
    stock_prices = prices.drop(columns=[config.INDEX_TICKER], errors="ignore")
    lookback = stock_prices.iloc[-config.LOOKBACK_DAYS:]
    daily_ret = lookback.pct_change()

    sectors = fundamentals["sector"] if "sector" in fundamentals.columns else pd.Series(dtype=object)

    selected: list[str] = []
    sector_counts: dict[str, int] = {}

    for ticker in ranked.index:
        if len(selected) >= top_n:
            break
        sector = sectors.get(ticker, "Unknown") or "Unknown"
        if sector_counts.get(sector, 0) >= max_per_sector:
            continue
        if ticker not in daily_ret.columns:
            continue
        if selected:
            corrs = []
            for other in selected:
                if other in daily_ret.columns:
                    c = daily_ret[ticker].corr(daily_ret[other])
                    if pd.notna(c):
                        corrs.append(c)
            if corrs and max(corrs) > max_pair_corr:
                continue
        selected.append(ticker)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1

    # Backfill from the ranked list (ignoring correlation cap) if the
    # diversification constraints left us short of top_n.
    if len(selected) < top_n:
        for ticker in ranked.index:
            if len(selected) >= top_n:
                break
            if ticker in selected or ticker not in daily_ret.columns:
                continue
            sector = sectors.get(ticker, "Unknown") or "Unknown"
            if sector_counts.get(sector, 0) >= max_per_sector:
                continue
            selected.append(ticker)
            sector_counts[sector] = sector_counts.get(sector, 0) + 1

    return selected


def risk_based_weights(tickers: list[str], prices: pd.DataFrame) -> pd.Series:
    """Inverse-volatility weighting, clamped to [MIN, MAX] single-name weight
    and iteratively renormalized.
    """
    stock_prices = prices[tickers].iloc[-config.LOOKBACK_DAYS:]
    ann_vol = stock_prices.pct_change().std() * np.sqrt(252)
    inv_vol = 1 / ann_vol.replace(0, np.nan)
    w = inv_vol / inv_vol.sum()

    for _ in range(20):
        clamped = w.clip(config.MIN_SINGLE_WEIGHT, config.MAX_SINGLE_WEIGHT)
        clamped = clamped / clamped.sum()
        if np.allclose(clamped.values, w.values, atol=1e-9):
            w = clamped
            break
        w = clamped
    return w


def construct_portfolio(
    scores: pd.DataFrame,
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    fundamentals: pd.DataFrame,
    capital: float,
    top_n: int,
    regime: dict,
    max_per_sector: int = config.DEFAULT_MAX_PER_SECTOR,
    min_liquidity_cr: float = config.DEFAULT_MIN_LIQUIDITY_CR,
    max_pair_corr: float = config.DEFAULT_MAX_PAIR_CORR,
    require_uptrend: bool = True,
) -> pd.DataFrame:
    gated = apply_gates(scores, prices, volumes, min_liquidity_cr, require_uptrend)
    ranked = gated.dropna(subset=["composite"]).sort_values("composite", ascending=False)

    selected = diversified_selection(ranked, prices, top_n, max_per_sector, max_pair_corr, fundamentals)
    valid = [t for t in selected if t in prices.columns]

    weights = risk_based_weights(valid, prices)
    effective_capital = capital * regime["deploy_pct"]
    current_px = prices[valid].iloc[-1]
    stops = factors.atr_stop_levels(prices[valid])

    port = pd.DataFrame({
        "weight": weights,
        "alloc_capital": weights * effective_capital,
        "close_price": current_px,
        "stop_loss": stops,
    })
    port["shares"] = np.floor(port["alloc_capital"] / port["close_price"]).astype(int)
    port["actual_cost"] = port["shares"] * port["close_price"]

    for col in ["momentum", "quality", "growth", "value", "low_vol", "composite"]:
        if col in scores.columns:
            port[f"{col}_z" if col != "composite" else col] = scores.loc[valid, col]
    port["liquidity_cr"] = gated["liquidity_cr"].reindex(valid)

    for col in ["name", "sector", "industry", "pe", "pb", "roe", "market_cap"]:
        if col in fundamentals.columns:
            port[col] = fundamentals[col].reindex(port.index)

    port.index = port.index.str.replace(".NS", "", regex=False)
    port = port.sort_values("composite", ascending=False)
    return port
