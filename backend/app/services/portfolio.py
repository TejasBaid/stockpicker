"""Portfolio tracking, exit planning and Indian tax treatment.

Positions are entered manually. This platform never reads the brokerage
account -- no holdings, positions or orders endpoint is called anywhere.

Valuation uses the latest stored daily close rather than a live quote, so the
request path makes no external call and works whether or not the market is
open. The nightly ingest keeps closes current.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, PermissionError_
from app.db.models.factors import FactorValue
from app.db.models.market import DailyBar, Instrument
from app.db.models.portfolio import ExitPlan, Portfolio, Position, Trade

# Indian capital gains: equity held over twelve months is long-term.
LTCG_HOLDING_DAYS = 365
STCG_RATE = 0.20
LTCG_RATE = 0.125
LTCG_EXEMPTION = Decimal("125000")  # per financial year, on long-term equity gains


def _latest_closes(db: Session, symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    rows = db.execute(
        select(DailyBar.symbol, DailyBar.close, DailyBar.date)
        .where(DailyBar.symbol.in_(symbols))
        .distinct(DailyBar.symbol)
        .order_by(DailyBar.symbol, DailyBar.date.desc())
    ).all()
    return {symbol: float(close) for symbol, close, _ in rows}


def _atr(db: Session, symbol: str, window: int = 14) -> float | None:
    """True-range ATR from stored bars.

    Uses the full true range -- max of today's range, and each of today's high
    and low against yesterday's close -- rather than close-to-close, which
    understates the stop distance on gappy names.
    """
    rows = db.execute(
        select(DailyBar.high, DailyBar.low, DailyBar.close)
        .where(DailyBar.symbol == symbol)
        .order_by(DailyBar.date.desc())
        .limit(window + 1)
    ).all()
    if len(rows) < window + 1:
        return None
    frame = pd.DataFrame(rows, columns=["high", "low", "close"]).iloc[::-1].astype(float)
    prev_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prev_close).abs(),
            (frame["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    value = true_range.tail(window).mean()
    return float(value) if pd.notna(value) else None


def get_portfolio(db: Session, portfolio_id: uuid.UUID, owner_id: uuid.UUID) -> Portfolio:
    portfolio = db.get(Portfolio, portfolio_id)
    if portfolio is None:
        raise NotFoundError("Portfolio not found.")
    if portfolio.owner_id != owner_id:
        raise PermissionError_("That portfolio belongs to someone else.")
    return portfolio


def list_portfolios(db: Session, owner_id: uuid.UUID) -> list[dict[str, Any]]:
    portfolios = db.scalars(
        select(Portfolio)
        .where(Portfolio.owner_id == owner_id, Portfolio.is_archived.is_(False))
        .order_by(Portfolio.created_at)
    ).all()
    return [summarise(db, p) for p in portfolios]


def summarise(db: Session, portfolio: Portfolio) -> dict[str, Any]:
    positions = [p for p in portfolio.positions if p.closed_on is None]
    closes = _latest_closes(db, [p.symbol for p in positions])

    invested = Decimal("0")
    market_value = Decimal("0")
    for position in positions:
        cost = position.quantity * position.avg_price
        price = Decimal(str(closes.get(position.symbol, 0.0)))
        invested += cost
        market_value += position.quantity * price

    pnl = market_value - invested
    return {
        "id": str(portfolio.id),
        "name": portfolio.name,
        "description": portfolio.description,
        "cash": float(portfolio.cash),
        "positions": len(positions),
        "invested": float(invested),
        "market_value": float(market_value),
        "total_value": float(market_value + portfolio.cash),
        "pnl": float(pnl),
        "pnl_pct": float(pnl / invested * 100) if invested else 0.0,
    }


def position_detail(db: Session, portfolio: Portfolio) -> list[dict[str, Any]]:
    positions = [p for p in portfolio.positions if p.closed_on is None]
    symbols = [p.symbol for p in positions]
    closes = _latest_closes(db, symbols)

    meta = db.execute(
        select(Instrument.symbol, Instrument.name, Instrument.sector).where(
            Instrument.symbol.in_(symbols)
        )
    ).all()
    names = {row[0]: row[1] for row in meta}
    sectors = {row[0]: row[2] for row in meta}

    total_value = sum(float(p.quantity) * closes.get(p.symbol, 0.0) for p in positions) or 1.0

    out: list[dict[str, Any]] = []
    for position in positions:
        price = closes.get(position.symbol, 0.0)
        cost = float(position.quantity * position.avg_price)
        value = float(position.quantity) * price
        held_days = (dt.date.today() - position.opened_on).days

        out.append(
            {
                "id": str(position.id),
                "symbol": position.symbol,
                "name": names.get(position.symbol),
                "sector": sectors.get(position.symbol),
                "quantity": float(position.quantity),
                "avg_price": float(position.avg_price),
                "last_price": price,
                "invested": round(cost, 2),
                "market_value": round(value, 2),
                "pnl": round(value - cost, 2),
                "pnl_pct": round((value / cost - 1) * 100, 2) if cost else 0.0,
                "weight_pct": round(value / total_value * 100, 2),
                "opened_on": position.opened_on.isoformat(),
                "held_days": held_days,
                "tax_status": "long-term" if held_days >= LTCG_HOLDING_DAYS else "short-term",
                "days_to_long_term": max(0, LTCG_HOLDING_DAYS - held_days),
                "thesis": position.thesis,
                "conviction": position.conviction,
                "exit_plan": _exit_plan_status(db, position, price),
                "factor_drift": _factor_drift(db, position),
            }
        )
    return sorted(out, key=lambda r: -r["market_value"])


def _exit_plan_status(db: Session, position: Position, price: float) -> dict[str, Any] | None:
    plan = position.exit_plan
    if plan is None:
        return None

    stop_price = float(plan.stop_price) if plan.stop_price is not None else None
    triggers: list[str] = []

    if stop_price is not None and price and price <= stop_price:
        triggers.append(f"Price {price:.2f} is at or below the stop at {stop_price:.2f}")

    if plan.time_stop_on and dt.date.today() >= plan.time_stop_on:
        triggers.append(f"Time stop reached ({plan.time_stop_on.isoformat()})")

    targets = plan.target_ladder or []
    hit = [t for t in targets if isinstance(t, dict) and price >= float(t.get("price", 1e18))]
    for t in hit:
        triggers.append(f"Target {t['price']} reached — trim {t.get('pct', 0)}%")

    return {
        "stop_type": plan.stop_type,
        "stop_price": stop_price,
        "stop_distance_pct": (
            round((price / stop_price - 1) * 100, 2) if stop_price and price else None
        ),
        "target_ladder": targets,
        "time_stop_on": plan.time_stop_on.isoformat() if plan.time_stop_on else None,
        "factor_decay_rules": plan.factor_decay_rules,
        "triggers": triggers,
        "notes": plan.notes,
    }


def _factor_drift(db: Session, position: Position) -> list[dict[str, Any]]:
    """How the factors behind the thesis have moved since entry.

    A position bought for quality and value should be reviewed when those
    ranks decay -- that is a reasoned exit rather than a reaction to price.
    """
    entry = position.entry_factors or {}
    if not entry:
        return []

    latest_as_of = db.scalar(select(func.max(FactorValue.as_of)))
    if latest_as_of is None:
        return []

    rows = db.execute(
        select(FactorValue.factor, FactorValue.decile).where(
            FactorValue.symbol == position.symbol,
            FactorValue.as_of == latest_as_of,
            FactorValue.factor.in_(list(entry)),
        )
    ).all()
    current: dict[str, int | None] = {row[0]: row[1] for row in rows}

    out = []
    for factor, entry_decile in entry.items():
        now = current.get(factor)
        if now is None or entry_decile is None:
            continue
        out.append(
            {
                "factor": factor,
                "entry_decile": int(entry_decile),
                "current_decile": int(now),
                # Deciles run 1 (best) to 10, so an increase is deterioration.
                "drift": int(now) - int(entry_decile),
            }
        )
    return sorted(out, key=lambda r: -r["drift"])


def suggest_stop(db: Session, symbol: str, *, multiple: float = 2.5) -> dict[str, Any]:
    closes = _latest_closes(db, [symbol])
    price = closes.get(symbol)
    atr = _atr(db, symbol)
    if price is None or atr is None:
        return {"symbol": symbol, "price": price, "atr": atr, "stop": None}
    stop = price - multiple * atr
    return {
        "symbol": symbol,
        "price": round(price, 2),
        "atr": round(atr, 2),
        "atr_multiple": multiple,
        "stop": round(stop, 2),
        "stop_distance_pct": round((stop / price - 1) * 100, 2),
    }


def realised_gains(db: Session, portfolio: Portfolio) -> dict[str, Any]:
    """Realised gains split short- and long-term, with tax estimated.

    Lots are matched first-in-first-out, which is what Indian brokers report
    and what the tax treatment assumes.
    """
    trades = db.scalars(
        select(Trade)
        .join(Position, Position.id == Trade.position_id)
        .where(Position.portfolio_id == portfolio.id)
        .order_by(Trade.traded_on, Trade.created_at)
    ).all()

    lots: dict[str, list[tuple[dt.date, Decimal, Decimal]]] = {}
    short_term = Decimal("0")
    long_term = Decimal("0")
    events: list[dict[str, Any]] = []

    positions = {p.id: p for p in portfolio.positions}
    for trade in trades:
        symbol = positions[trade.position_id].symbol
        queue = lots.setdefault(symbol, [])
        if trade.side == "BUY":
            queue.append((trade.traded_on, trade.quantity, trade.price))
            continue

        remaining = trade.quantity
        while remaining > 0 and queue:
            bought_on, qty, cost = queue[0]
            used = min(qty, remaining)
            gain = (trade.price - cost) * used
            held = (trade.traded_on - bought_on).days
            if held >= LTCG_HOLDING_DAYS:
                long_term += gain
            else:
                short_term += gain
            events.append(
                {
                    "symbol": symbol,
                    "sold_on": trade.traded_on.isoformat(),
                    "quantity": float(used),
                    "gain": float(gain),
                    "held_days": held,
                    "term": "long" if held >= LTCG_HOLDING_DAYS else "short",
                }
            )
            remaining -= used
            if used == qty:
                queue.pop(0)
            else:
                queue[0] = (bought_on, qty - used, cost)

    taxable_long = max(Decimal("0"), long_term - LTCG_EXEMPTION)
    tax = short_term * Decimal(str(STCG_RATE)) + taxable_long * Decimal(str(LTCG_RATE))

    return {
        "short_term_gain": float(short_term),
        "long_term_gain": float(long_term),
        "ltcg_exemption_used": float(min(max(long_term, Decimal("0")), LTCG_EXEMPTION)),
        "estimated_tax": float(max(Decimal("0"), tax)),
        "stcg_rate_pct": STCG_RATE * 100,
        "ltcg_rate_pct": LTCG_RATE * 100,
        "events": events[-50:],
        "note": (
            "First-in-first-out lot matching, as Indian brokers report. "
            "Estimates only — not tax advice."
        ),
    }


def capture_entry_factors(db: Session, symbol: str) -> dict[str, int]:
    """Snapshot the current factor deciles, so drift can be measured later."""
    latest_as_of = db.scalar(select(func.max(FactorValue.as_of)))
    if latest_as_of is None:
        return {}
    rows = db.execute(
        select(FactorValue.factor, FactorValue.decile).where(
            FactorValue.symbol == symbol,
            FactorValue.as_of == latest_as_of,
            FactorValue.decile.is_not(None),
        )
    ).all()
    return {factor: int(decile) for factor, decile in rows}


def rebalance_proposal(
    db: Session, portfolio: Portfolio, targets: dict[str, float]
) -> list[dict[str, Any]]:
    """Buy/sell list to move from the current portfolio to target weights."""
    positions = {p.symbol: p for p in portfolio.positions if p.closed_on is None}
    symbols = sorted(set(positions) | set(targets))
    closes = _latest_closes(db, symbols)

    total = sum(float(p.quantity) * closes.get(p.symbol, 0.0) for p in positions.values()) + float(
        portfolio.cash
    )

    proposals = []
    for symbol in symbols:
        price = closes.get(symbol)
        if not price:
            continue
        current_value = float(positions[symbol].quantity) * price if symbol in positions else 0.0
        target_value = total * targets.get(symbol, 0.0)
        delta_value = target_value - current_value
        if abs(delta_value) < max(total * 0.005, 1000):  # ignore noise
            continue
        proposals.append(
            {
                "symbol": symbol,
                "side": "BUY" if delta_value > 0 else "SELL",
                "price": round(price, 2),
                "shares": int(abs(delta_value) // price),
                "value": round(abs(delta_value), 2),
                "current_weight_pct": round(current_value / total * 100, 2) if total else 0.0,
                "target_weight_pct": round(targets.get(symbol, 0.0) * 100, 2),
            }
        )
    return sorted(proposals, key=lambda r: -r["value"])


def create_exit_plan(
    db: Session,
    position: Position,
    *,
    stop_type: str | None = None,
    stop_value: float | None = None,
    stop_price: float | None = None,
    target_ladder: list[dict[str, Any]] | None = None,
    time_stop_on: dt.date | None = None,
    factor_decay_rules: dict[str, Any] | None = None,
    notes: str | None = None,
) -> ExitPlan:
    plan = position.exit_plan or ExitPlan(position_id=position.id)

    # An ATR stop is resolved to a price at planning time so it is a commitment,
    # not a moving target that drifts down with the position.
    if stop_type == "atr" and stop_price is None:
        suggestion = suggest_stop(db, position.symbol, multiple=stop_value or 2.5)
        stop_price = suggestion.get("stop")

    plan.stop_type = stop_type
    plan.stop_value = stop_value
    plan.stop_price = Decimal(str(stop_price)) if stop_price is not None else None
    plan.target_ladder = target_ladder
    plan.time_stop_on = time_stop_on
    plan.factor_decay_rules = factor_decay_rules
    plan.notes = notes

    db.add(plan)
    db.commit()
    return plan
