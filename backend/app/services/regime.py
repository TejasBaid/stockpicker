"""Market regime: how much of your capital the market deserves right now.

The prototype had a three-state model (above both moving averages, above one,
below both) mapping to fixed deployment percentages. That is a reasonable
skeleton but it ignores two things that matter: how *broad* the advance is, and
how violent conditions are. A market where the index is above its moving
averages on the back of eight stocks is not the same as one where two-thirds of
the universe is trending, and neither deserves the same allocation.

So four signals are scored and blended:

* **trend** -- the index against its own 50- and 200-day averages
* **breadth** -- what fraction of the universe is above its own 200-day average
* **drawdown** -- how far the index sits below its 52-week high
* **volatility** -- realised volatility against its own two-year history

The output is a suggested deployment percentage and a staging plan. It is a
starting point for a decision, not a signal to obey: the reasoning is returned
alongside the number so you can disagree with it on specifics.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.market import DailyBar

BENCHMARK = "NIFTY"
TRADING_DAYS_YEAR = 252

State = Literal["risk_on", "neutral", "risk_off"]

# Deployment floors and ceilings. Never zero: sitting entirely in cash is a
# market-timing bet of its own, and a bad one over long horizons.
MIN_DEPLOY = 0.30
MAX_DEPLOY = 1.00


@dataclass
class Regime:
    state: State
    score: float  # 0 (hostile) .. 1 (favourable)
    deploy_pct: float
    signals: list[dict[str, Any]]
    tranches: list[dict[str, Any]]
    as_of: dt.date
    note: str


def _index_series(db: Session, lookback_days: int = 900) -> pd.Series:
    start = dt.date.today() - dt.timedelta(days=lookback_days)
    rows = db.execute(
        select(DailyBar.date, DailyBar.close)
        .where(DailyBar.symbol == BENCHMARK, DailyBar.date >= start)
        .order_by(DailyBar.date)
    ).all()
    if not rows:
        return pd.Series(dtype=float)
    series = pd.Series({d: float(c) for d, c in rows})
    series.index = pd.to_datetime(series.index)
    return series


def _breadth(db: Session, symbols: list[str]) -> float | None:
    """Fraction of the universe trading above its own 200-day average."""
    if not symbols:
        return None
    start = dt.date.today() - dt.timedelta(days=400)
    rows = db.execute(
        select(DailyBar.symbol, DailyBar.date, DailyBar.close)
        .where(DailyBar.symbol.in_(symbols), DailyBar.date >= start)
        .order_by(DailyBar.date)
    ).all()
    if not rows:
        return None
    frame = pd.DataFrame(rows, columns=["symbol", "date", "close"])
    wide = frame.pivot_table(index="date", columns="symbol", values="close").ffill()
    if len(wide) < 200:
        return None
    sma = wide.tail(200).mean()
    latest = wide.iloc[-1]
    above = (latest > sma).sum()
    total = latest.notna().sum()
    return float(above / total) if total else None


def assess(db: Session, universe_symbols: list[str] | None = None) -> Regime:
    index = _index_series(db)
    today = dt.date.today()
    if index.empty or len(index) < 220:
        return Regime(
            state="neutral",
            score=0.5,
            deploy_pct=0.60,
            signals=[],
            tranches=_tranches(0.60),
            as_of=today,
            note="Not enough index history to judge conditions; defaulting to a middling stance.",
        )

    as_of = index.index[-1].date()
    price = float(index.iloc[-1])
    sma50 = float(index.tail(50).mean())
    sma200 = float(index.tail(200).mean())
    high52 = float(index.tail(TRADING_DAYS_YEAR).max())

    signals: list[dict[str, Any]] = []

    # 1. Trend -----------------------------------------------------------
    above50, above200 = price > sma50, price > sma200
    golden = sma50 > sma200
    trend_score = 0.2 + 0.3 * above200 + 0.3 * above50 + 0.2 * golden
    signals.append(
        {
            "key": "trend",
            "label": "Index trend",
            "score": round(trend_score, 2),
            "detail": (
                f"Nifty {price:,.0f} is {'above' if above50 else 'below'} its 50-day "
                f"({sma50:,.0f}) and {'above' if above200 else 'below'} its 200-day "
                f"({sma200:,.0f}); the 50-day is {'above' if golden else 'below'} the 200-day."
            ),
        }
    )

    # 2. Drawdown from the 52-week high -----------------------------------
    drawdown = price / high52 - 1.0
    # Flat until -5%, then falling away; a 20% drawdown scores zero.
    dd_score = float(np.clip(1.0 + (drawdown + 0.05) / 0.15, 0.0, 1.0))
    signals.append(
        {
            "key": "drawdown",
            "label": "Distance from the high",
            "score": round(dd_score, 2),
            "detail": (
                f"{drawdown * 100:.1f}% from the 52-week high of {high52:,.0f}."
                if drawdown < -0.005
                else "At or near the 52-week high."
            ),
        }
    )

    # 3. Volatility against its own history --------------------------------
    returns = index.pct_change(fill_method=None).dropna()
    recent_vol = float(returns.tail(21).std(ddof=0) * np.sqrt(TRADING_DAYS_YEAR))
    history = returns.rolling(21).std(ddof=0).dropna() * np.sqrt(TRADING_DAYS_YEAR)
    vol_pctile = float((history < recent_vol).mean()) if len(history) > 60 else 0.5
    vol_score = float(np.clip(1.0 - vol_pctile, 0.0, 1.0))
    signals.append(
        {
            "key": "volatility",
            "label": "Volatility",
            "score": round(vol_score, 2),
            "detail": (
                f"Realised volatility {recent_vol * 100:.1f}%, higher than "
                f"{vol_pctile * 100:.0f}% of the past two years."
            ),
        }
    )

    # 4. Breadth ----------------------------------------------------------
    breadth = _breadth(db, universe_symbols or [])
    if breadth is None:
        breadth_score = 0.5
        breadth_detail = "Not enough constituent history to measure breadth."
    else:
        # Around half the universe above its own 200-day average is an
        # ordinary market, not a strong one: 30% scores zero, 50% scores a
        # half, 70% and up scores full. Dividing by a 60% ceiling instead
        # would call a perfectly average tape "strong".
        breadth_score = float(np.clip((breadth - 0.30) / 0.40, 0.0, 1.0))
        breadth_detail = f"{breadth * 100:.0f}% of the universe is above its own 200-day average."
    signals.append(
        {
            "key": "breadth",
            "label": "Breadth",
            "score": round(breadth_score, 2),
            "detail": breadth_detail,
        }
    )

    # Trend and breadth carry the most weight: they describe the market you are
    # actually buying, while drawdown and volatility describe how it feels.
    weights = {"trend": 0.35, "breadth": 0.30, "drawdown": 0.20, "volatility": 0.15}
    score = sum(s["score"] * weights[s["key"]] for s in signals)

    deploy = MIN_DEPLOY + (MAX_DEPLOY - MIN_DEPLOY) * score
    deploy = round(min(MAX_DEPLOY, max(MIN_DEPLOY, deploy)), 2)

    if score >= 0.66:
        state: State = "risk_on"
        note = "Conditions are constructive. Deploy close to fully, in a couple of tranches."
    elif score >= 0.40:
        state = "neutral"
        note = "Mixed conditions. Deploy most of it, but stage entries and keep some dry powder."
    else:
        state = "risk_off"
        note = (
            "Conditions are hostile. Deploy a minority now and stage the rest — "
            "but staying entirely in cash is its own bet, and usually a losing one."
        )

    return Regime(
        state=state,
        score=round(score, 3),
        deploy_pct=deploy,
        signals=signals,
        tranches=_tranches(deploy),
        as_of=as_of,
        note=note,
    )


def _tranches(deploy_pct: float) -> list[dict[str, Any]]:
    """Stage the entry. Weaker conditions mean smaller first bites and longer
    gaps, so a bad call costs less and a falling market is bought into rather
    than chased."""
    if deploy_pct >= 0.85:
        plan = [(0.60, 0), (0.40, 21)]
    elif deploy_pct >= 0.60:
        plan = [(0.45, 0), (0.30, 21), (0.25, 45)]
    else:
        plan = [(0.35, 0), (0.35, 30), (0.30, 60)]

    today = dt.date.today()
    return [
        {
            "share": share,
            "in_days": days,
            "on_or_after": (today + dt.timedelta(days=days)).isoformat(),
            "label": "Now" if days == 0 else f"In about {days} days",
        }
        for share, days in plan
    ]
