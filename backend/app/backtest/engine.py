"""Point-in-time walk-forward backtester.

At every rebalance date the engine rebuilds the panel *as of that date* and
recomputes the strategy's factors from it. It never reuses the precomputed
factor table, because that table describes today. Every fundamental read is
gated on ``known_on <= as_of``, so a result announced on 24 April cannot
influence a portfolio formed on 1 April.

That discipline is the whole point. A backtest that quietly uses tomorrow's
earnings looks wonderful and teaches you nothing.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd
import structlog
from sqlalchemy.orm import Session

from app.backtest.costs import DEFAULT_COSTS, CostModel
from app.backtest.metrics import compute_metrics, monthly_returns
from app.db.models.market import DailyBar
from app.factors.panel import BENCHMARK_SYMBOL, build_panel
from app.factors.precompute import score_factor
from app.factors.registry import all_factors
from app.screener.service import Filter

log = structlog.get_logger(__name__)

Frequency = Literal["monthly", "quarterly", "yearly"]
Weighting = Literal["equal", "inverse_vol"]

FREQ_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}


@dataclass
class BacktestConfig:
    weights: dict[str, float]
    start: dt.date
    end: dt.date
    universe_symbols: list[str]
    filters: list[Filter] = field(default_factory=list)
    holdings: int = 20
    frequency: Frequency = "quarterly"
    weighting: Weighting = "equal"
    max_per_sector: int | None = 4
    initial_capital: float = 1_000_000.0
    costs: CostModel = DEFAULT_COSTS
    basis: Literal["zscore", "sector_zscore"] = "sector_zscore"


def rebalance_dates(start: dt.date, end: dt.date, frequency: Frequency) -> list[dt.date]:
    step = FREQ_MONTHS[frequency]
    out: list[dt.date] = []
    year, month = start.year, start.month
    while True:
        day = dt.date(year, month, min(start.day, 28))
        if day > end:
            break
        if day >= start:
            out.append(day)
        month += step
        while month > 12:
            month -= 12
            year += 1
    return out


def _load_prices(db: Session, symbols: list[str], start: dt.date, end: dt.date) -> pd.DataFrame:
    from sqlalchemy import select

    rows = db.execute(
        select(DailyBar.symbol, DailyBar.date, DailyBar.close)
        .where(
            DailyBar.symbol.in_([*symbols, BENCHMARK_SYMBOL]),
            DailyBar.date >= start,
            DailyBar.date <= end,
        )
        .order_by(DailyBar.date)
    ).all()
    frame = pd.DataFrame(rows, columns=["symbol", "date", "close"])
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.pivot_table(index="date", columns="symbol", values="close").ffill()


def select_portfolio(
    db: Session, config: BacktestConfig, as_of: dt.date
) -> tuple[list[str], dict[str, Any]]:
    """Run the strategy as it would have run on ``as_of``."""
    registry = all_factors()
    needed = sorted(set(config.weights) | {f.factor for f in config.filters})

    panel = build_panel(db, config.universe_symbols, as_of)
    if panel.prices.empty:
        return [], {"reason": "no prices"}

    scores: dict[str, pd.Series] = {}
    raws: dict[str, pd.Series] = {}
    for name in needed:
        factor = registry.get(name)
        if factor is None:
            continue
        try:
            raw = factor.compute(panel)
        except Exception as exc:
            log.warning(
                "backtest.factor_failed", factor=name, as_of=str(as_of), error=str(exc)[:150]
            )
            continue
        scored = score_factor(factor, raw, panel)
        scores[name] = scored[config.basis]
        raws[name] = scored["raw"]

    if not scores:
        return [], {"reason": "no factors computed"}

    total_weight = sum(abs(w) for w in config.weights.values()) or 1.0
    composite = pd.Series(0.0, index=pd.Index(panel.symbols, name="symbol"))
    for name, weight in config.weights.items():
        if name in scores:
            composite += scores[name].fillna(0.0) * (weight / total_weight)

    eligible = pd.Series(True, index=composite.index)
    for f in config.filters:
        column = raws.get(f.factor)
        if column is None:
            continue
        eligible &= column.map(lambda v, flt=f: flt.passes(v))

    ranked = composite[eligible].sort_values(ascending=False)

    selected: list[str] = []
    per_sector: dict[str, int] = {}
    for symbol in ranked.index:
        sector = str(panel.sectors.get(symbol) or "Unknown")
        if config.max_per_sector is not None and per_sector.get(sector, 0) >= config.max_per_sector:
            continue
        selected.append(symbol)
        per_sector[sector] = per_sector.get(sector, 0) + 1
        if len(selected) >= config.holdings:
            break

    return selected, {"eligible": int(eligible.sum()), "scored": int(composite.notna().sum())}


def _target_weights(
    symbols: list[str], prices: pd.DataFrame, as_of: pd.Timestamp, weighting: Weighting
) -> pd.Series:
    if not symbols:
        return pd.Series(dtype=float)
    if weighting == "equal":
        return pd.Series(1.0 / len(symbols), index=symbols)

    window = prices.loc[:as_of, symbols].tail(126)
    vol = window.pct_change(fill_method=None).std(ddof=0)
    inv = 1.0 / vol.replace(0.0, np.nan)
    inv = inv.fillna(inv.median())
    if inv.sum() == 0 or not np.isfinite(inv.sum()):
        return pd.Series(1.0 / len(symbols), index=symbols)
    return inv / inv.sum()


def _equal_weight_universe_curve(prices: pd.DataFrame, symbols: list[str]) -> pd.Series:
    """Buy-and-hold, equal-weighted across the whole universe.

    This is the benchmark that actually matters. The Nifty 50 is large-cap
    only, so a Nifty 200 strategy beats it whenever mid caps lead -- and that
    shows up as "alpha" even for a strategy with no skill in it at all. Measured
    against this line instead, only genuine selection ability counts.
    """
    columns = [s for s in symbols if s in prices.columns]
    if not columns:
        return pd.Series(dtype=float)
    returns = prices[columns].pct_change(fill_method=None)
    # Equal weight, rebalanced daily: the mean cross-sectional return.
    mean_return = returns.mean(axis=1, skipna=True).fillna(0.0)
    return (1.0 + mean_return).cumprod()


def run_backtest(db: Session, config: BacktestConfig) -> dict[str, Any]:
    prices = _load_prices(db, config.universe_symbols, config.start, config.end)
    if prices.empty:
        return {"error": "No price history for the requested period."}

    dates = rebalance_dates(config.start, config.end, config.frequency)
    if not dates:
        return {"error": "The period is too short for the chosen rebalance frequency."}

    cash = config.initial_capital
    holdings: dict[str, float] = {}  # symbol -> share count
    equity_points: list[tuple[pd.Timestamp, float]] = []
    trades: list[dict[str, Any]] = []
    rebalances: list[dict[str, Any]] = []
    total_costs = 0.0

    trading_days = prices.index
    for i, rebalance_day in enumerate(dates):
        ts = pd.Timestamp(rebalance_day)
        available = trading_days[trading_days <= ts]
        if available.empty:
            continue
        trade_day = available[-1]

        selected, info = select_portfolio(db, config, rebalance_day)
        row = prices.loc[trade_day]

        portfolio_value = cash + sum(
            qty * float(row.get(sym, np.nan) or 0.0) for sym, qty in holdings.items()
        )
        if not np.isfinite(portfolio_value) or portfolio_value <= 0:
            break

        targets = _target_weights(selected, prices, trade_day, config.weighting)
        target_value = {s: portfolio_value * w for s, w in targets.items()}

        # Sell what is no longer wanted, or trim what is overweight.
        for symbol in list(holdings):
            price = float(row.get(symbol, np.nan) or 0.0)
            if not np.isfinite(price) or price <= 0:
                continue
            desired_qty = target_value.get(symbol, 0.0) / price
            delta = desired_qty - holdings[symbol]
            if delta < 0:
                value = -delta * price
                fee = config.costs.cost(value, "SELL")
                cash += value - fee
                total_costs += fee
                holdings[symbol] += delta
                trades.append(
                    {
                        "date": trade_day.date().isoformat(),
                        "symbol": symbol,
                        "side": "SELL",
                        "value": round(value, 2),
                        "cost": round(fee, 2),
                    }
                )
                if holdings[symbol] <= 1e-9:
                    del holdings[symbol]

        # Then buy into the new targets.
        for symbol, value_target in target_value.items():
            price = float(row.get(symbol, np.nan) or 0.0)
            if not np.isfinite(price) or price <= 0:
                continue
            desired_qty = value_target / price
            delta = desired_qty - holdings.get(symbol, 0.0)
            if delta > 0:
                value = delta * price
                fee = config.costs.cost(value, "BUY")
                if value + fee > cash:
                    value = max(0.0, cash - fee)
                    delta = value / price
                if value <= 0:
                    continue
                cash -= value + fee
                total_costs += fee
                holdings[symbol] = holdings.get(symbol, 0.0) + delta
                trades.append(
                    {
                        "date": trade_day.date().isoformat(),
                        "symbol": symbol,
                        "side": "BUY",
                        "value": round(value, 2),
                        "cost": round(fee, 2),
                    }
                )

        rebalances.append(
            {
                "date": trade_day.date().isoformat(),
                "holdings": selected,
                "count": len(selected),
                "portfolio_value": round(portfolio_value, 2),
                **info,
            }
        )

        # Mark to market daily until the next rebalance.
        next_ts = pd.Timestamp(dates[i + 1]) if i + 1 < len(dates) else trading_days[-1]
        window = trading_days[(trading_days >= trade_day) & (trading_days <= next_ts)]
        for day in window:
            day_row = prices.loc[day]
            value = cash + sum(
                qty * float(day_row.get(sym, np.nan) or 0.0) for sym, qty in holdings.items()
            )
            if np.isfinite(value):
                equity_points.append((day, value))

    if not equity_points:
        return {"error": "The backtest produced no positions."}

    curve = pd.Series(dict(equity_points)).sort_index()
    curve = curve[~curve.index.duplicated(keep="last")]

    benchmark = (
        prices[BENCHMARK_SYMBOL].reindex(curve.index).ffill()
        if BENCHMARK_SYMBOL in prices.columns
        else pd.Series(dtype=float)
    )

    metrics = compute_metrics(curve / config.initial_capital, benchmark)

    universe_curve = (
        _equal_weight_universe_curve(prices, config.universe_symbols).reindex(curve.index).ffill()
    )
    if not universe_curve.empty and universe_curve.notna().any():
        base = universe_curve.dropna().iloc[0]
        if base > 0:
            normalised = universe_curve / base
            universe_metrics = compute_metrics(normalised)
            metrics["universe_cagr_pct"] = universe_metrics.get("cagr_pct")
            metrics["universe_max_drawdown_pct"] = universe_metrics.get("max_drawdown_pct")
            if metrics.get("cagr_pct") is not None and metrics["universe_cagr_pct"] is not None:
                metrics["alpha_vs_universe_pct"] = round(
                    metrics["cagr_pct"] - metrics["universe_cagr_pct"], 2
                )

    metrics["total_costs"] = round(total_costs, 2)
    metrics["cost_drag_pct"] = round(100 * total_costs / config.initial_capital, 2)
    metrics["trades"] = len(trades)
    metrics["rebalances"] = len(rebalances)

    return {
        "start": config.start.isoformat(),
        "end": config.end.isoformat(),
        "frequency": config.frequency,
        "holdings": config.holdings,
        "initial_capital": config.initial_capital,
        "final_value": round(float(curve.iloc[-1]), 2),
        "metrics": metrics,
        "equity_curve": [
            {"date": ts.date().isoformat(), "value": round(float(v), 2)} for ts, v in curve.items()
        ],
        "benchmark_curve": (
            [
                {
                    "date": ts.date().isoformat(),
                    "value": round(float(v / benchmark.iloc[0] * config.initial_capital), 2),
                }
                for ts, v in benchmark.items()
                if np.isfinite(v)
            ]
            if not benchmark.empty and benchmark.iloc[0] > 0
            else []
        ),
        "universe_curve": (
            [
                {
                    "date": ts.date().isoformat(),
                    "value": round(
                        float(v / universe_curve.dropna().iloc[0] * config.initial_capital), 2
                    ),
                }
                for ts, v in universe_curve.items()
                if np.isfinite(v)
            ]
            if not universe_curve.empty and universe_curve.notna().any()
            else []
        ),
        "monthly_returns": monthly_returns(curve),
        "rebalance_log": rebalances,
        "recent_trades": trades[-100:],
    }
