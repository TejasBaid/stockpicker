from __future__ import annotations

import numpy as np
import pandas as pd

from . import config, factors, portfolio, regime as regime_mod


def run_backtest(
    prices_full: pd.DataFrame,
    volumes: pd.DataFrame,
    fundamentals: pd.DataFrame,
    weights: dict,
    top_n: int = 10,
    capital: float = 200_000,
    max_per_sector: int = config.DEFAULT_MAX_PER_SECTOR,
    min_liquidity_cr: float = config.DEFAULT_MIN_LIQUIDITY_CR,
) -> dict:
    """Rolling quarterly walk-forward backtest. Uses only data available up
    to each rebalance date (no lookahead) — fundamentals are treated as
    static (a known limitation without point-in-time fundamentals history).
    """
    stock_prices = prices_full.drop(columns=[config.INDEX_TICKER], errors="ignore")
    min_rows = config.LOOKBACK_DAYS + 65
    if len(prices_full) < min_rows:
        return {}

    start_idx = config.LOOKBACK_DAYS + 1
    rebal_dates = pd.date_range(stock_prices.index[start_idx], stock_prices.index[-1], freq="QE")
    rebal_dates = [d for d in rebal_dates if d in stock_prices.index]

    equity = [capital]
    dates = [stock_prices.index[start_idx]]
    holdings: dict[str, float] = {}
    cash = capital  # uninvested (regime-buffered) portion, carried between rebalances

    for i, rebal_date in enumerate(rebal_dates):
        loc = stock_prices.index.get_loc(rebal_date)
        slice_prices = prices_full.iloc[: loc + 1]
        slice_volumes = volumes.iloc[: loc + 1]

        idx_slice = slice_prices[config.INDEX_TICKER].dropna()
        if len(idx_slice) < config.REGIME_SMA_SLOW:
            continue
        reg = regime_mod.detect_regime(idx_slice)

        scores = factors.build_scores(slice_prices, fundamentals, weights)
        gated = portfolio.apply_gates(scores, slice_prices, slice_volumes, min_liquidity_cr, require_uptrend=True)
        ranked = gated.dropna(subset=["composite"]).sort_values("composite", ascending=False)
        selected = portfolio.diversified_selection(
            ranked, slice_prices, top_n, max_per_sector, config.DEFAULT_MAX_PAIR_CORR, fundamentals
        )
        selected = [t for t in selected if t in slice_prices.columns]
        if not selected:
            continue

        # Total equity = current holdings value + cash carried from last rebalance.
        # Only `deploy_pct` of the TOTAL goes to work; the rest stays as cash and
        # is re-evaluated for deployment at the next rebalance (it is not lost).
        invested_value = sum(holdings.get(t, 0) * slice_prices[t].iloc[-1] for t in holdings)
        total_equity = invested_value + cash
        if total_equity <= 0:
            total_equity = equity[-1]

        effective_val = total_equity * reg["deploy_pct"]
        cash = total_equity - effective_val
        w = portfolio.risk_based_weights(selected, slice_prices)

        holdings = {}
        for t in selected:
            wt = w.get(t, 0)
            px = slice_prices[t].iloc[-1]
            shares = np.floor(wt * effective_val / px)
            holdings[t] = shares
            cash += (wt * effective_val) - (shares * px)  # unspent fractional-share residual

        next_rebal = rebal_dates[i + 1] if i + 1 < len(rebal_dates) else stock_prices.index[-1]
        sim_cols = [t for t in holdings if t in stock_prices.columns]
        sim_slice = stock_prices.loc[rebal_date:next_rebal, sim_cols].dropna(how="all", axis=1)

        for day in sim_slice.index[1:]:
            day_val = cash + sum(holdings.get(t, 0) * sim_slice.loc[day, t] for t in holdings if t in sim_slice.columns)
            equity.append(day_val)
            dates.append(day)

    if len(equity) < 2:
        return {}

    equity_series = pd.Series(equity, index=dates).sort_index()
    total_days = (equity_series.index[-1] - equity_series.index[0]).days
    n_years = max(total_days / 365.25, 0.01)
    cagr = (equity_series.iloc[-1] / equity_series.iloc[0]) ** (1 / n_years) - 1

    daily_ret = equity_series.pct_change().dropna()
    sharpe = (daily_ret.mean() / daily_ret.std()) * np.sqrt(252) if daily_ret.std() > 0 else 0

    roll_max = equity_series.cummax()
    drawdown = (equity_series - roll_max) / roll_max
    max_dd = drawdown.min()
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    neg_ret = daily_ret[daily_ret < 0]
    sortino = (daily_ret.mean() / neg_ret.std()) * np.sqrt(252) if len(neg_ret) > 0 and neg_ret.std() > 0 else 0

    idx_full = prices_full[config.INDEX_TICKER].loc[equity_series.index[0]:equity_series.index[-1]]
    bench_cagr = (idx_full.iloc[-1] / idx_full.iloc[0]) ** (1 / n_years) - 1 if len(idx_full) > 1 else 0

    return {
        "equity_curve": [{"date": d.strftime("%Y-%m-%d"), "value": float(v)} for d, v in equity_series.items()],
        "benchmark_curve": [
            {"date": d.strftime("%Y-%m-%d"), "value": float(v / idx_full.iloc[0] * capital)}
            for d, v in idx_full.items()
        ],
        "cagr": float(cagr),
        "bench_cagr": float(bench_cagr),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "max_dd": float(max_dd),
        "calmar": float(calmar),
        "n_years": float(n_years),
        "final_val": float(equity_series.iloc[-1]),
        "start_val": float(equity_series.iloc[0]),
    }
