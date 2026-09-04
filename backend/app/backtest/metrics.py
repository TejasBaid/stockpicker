"""Tearsheet metrics."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

TRADING_DAYS = 252
RISK_FREE_ANNUAL = 0.065  # Indian 10-year is a more honest hurdle than zero


def _annualised_return(curve: pd.Series) -> float:
    if len(curve) < 2 or curve.iloc[0] <= 0:
        return 0.0
    years = (curve.index[-1] - curve.index[0]).days / 365.25
    if years <= 0:
        return 0.0
    return float((curve.iloc[-1] / curve.iloc[0]) ** (1 / years) - 1.0)


def max_drawdown(curve: pd.Series) -> float:
    if curve.empty:
        return 0.0
    return float((curve / curve.cummax() - 1.0).min())


def compute_metrics(curve: pd.Series, benchmark: pd.Series | None = None) -> dict[str, Any]:
    """Standard performance statistics from an equity curve."""
    if curve.empty or len(curve) < 2:
        return {}

    returns = curve.pct_change(fill_method=None).dropna()
    cagr = _annualised_return(curve)
    vol = float(returns.std(ddof=0) * np.sqrt(TRADING_DAYS))
    downside = returns[returns < 0]
    downside_vol = float(downside.std(ddof=0) * np.sqrt(TRADING_DAYS)) if len(downside) else 0.0
    dd = max_drawdown(curve)

    excess = cagr - RISK_FREE_ANNUAL
    metrics: dict[str, Any] = {
        "total_return_pct": round((curve.iloc[-1] / curve.iloc[0] - 1.0) * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "volatility_pct": round(vol * 100, 2),
        "sharpe": round(excess / vol, 2) if vol else None,
        "sortino": round(excess / downside_vol, 2) if downside_vol else None,
        "max_drawdown_pct": round(dd * 100, 2),
        "calmar": round(cagr / abs(dd), 2) if dd else None,
        "best_day_pct": round(float(returns.max()) * 100, 2),
        "worst_day_pct": round(float(returns.min()) * 100, 2),
        "positive_days_pct": round(float((returns > 0).mean()) * 100, 1),
        "days": len(curve),
    }

    if benchmark is not None and not benchmark.empty:
        aligned = benchmark.reindex(curve.index).ffill()
        if aligned.notna().sum() > 1 and aligned.iloc[0] > 0:
            bench_curve = aligned / aligned.iloc[0]
            bench_cagr = _annualised_return(bench_curve)
            metrics["benchmark_cagr_pct"] = round(bench_cagr * 100, 2)
            metrics["benchmark_total_return_pct"] = round(
                (bench_curve.iloc[-1] / bench_curve.iloc[0] - 1.0) * 100, 2
            )
            metrics["benchmark_max_drawdown_pct"] = round(max_drawdown(bench_curve) * 100, 2)
            metrics["alpha_pct"] = round((cagr - bench_cagr) * 100, 2)

            bench_returns = bench_curve.pct_change(fill_method=None).dropna()
            joint = pd.concat([returns, bench_returns], axis=1).dropna()
            if len(joint) > 30:
                var = joint.iloc[:, 1].var(ddof=0)
                if var:
                    metrics["beta"] = round(float(joint.iloc[:, 0].cov(joint.iloc[:, 1]) / var), 2)
                tracking = (joint.iloc[:, 0] - joint.iloc[:, 1]).std(ddof=0) * np.sqrt(TRADING_DAYS)
                if tracking:
                    metrics["information_ratio"] = round((cagr - bench_cagr) / float(tracking), 2)

    return metrics


def monthly_returns(curve: pd.Series) -> list[dict[str, Any]]:
    if curve.empty:
        return []
    monthly = curve.resample("ME").last().pct_change(fill_method=None).dropna()
    return [
        {"month": ts.strftime("%Y-%m"), "return_pct": round(float(v) * 100, 2)}
        for ts, v in monthly.items()
    ]
