"""Corporate actions.

The vendor populates dividends only -- its bonus, split and rights arrays come
back empty for every symbol in this universe, so this module is honest about
covering payouts and nothing else.

Two uses, both of which change a buying decision:

* **Upcoming ex-dates.** Buying just before a stock goes ex-dividend is usually
  worse than buying just after for an Indian taxable investor: the price falls
  by roughly the dividend, and since 2020 the dividend is taxed at your slab
  rate rather than being tax-free. You get the same economics and a tax bill.
* **Dividend record.** Actual payouts give a trailing yield that can be checked
  against the vendor's own figure, plus a consistency count -- how many of the
  past five years the company actually paid.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.fundamentals import CorporateAction
from app.db.models.market import DailyBar

# Inside this window the ex-date is close enough to be worth waiting out.
EX_DATE_WARNING_DAYS = 10


def upcoming(db: Session, symbols: list[str], within_days: int = 45) -> dict[str, list[dict]]:
    if not symbols:
        return {}
    today = dt.date.today()
    rows = db.scalars(
        select(CorporateAction)
        .where(
            CorporateAction.symbol.in_(symbols),
            CorporateAction.ex_date >= today,
            CorporateAction.ex_date <= today + dt.timedelta(days=within_days),
        )
        .order_by(CorporateAction.ex_date)
    ).all()

    out: dict[str, list[dict[str, Any]]] = {}
    for action in rows:
        assert action.ex_date is not None
        days = (action.ex_date - today).days
        out.setdefault(action.symbol, []).append(
            {
                "type": action.action_type,
                "ex_date": action.ex_date.isoformat(),
                "days_away": days,
                "value": float(action.value) if action.value is not None else None,
                "remarks": action.remarks,
                "imminent": days <= EX_DATE_WARNING_DAYS,
            }
        )
    return out


def trailing_dividends(db: Session, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Dividends actually paid over the last twelve months, and consistency
    over five years, computed from the payout record rather than a vendor
    ratio."""
    if not symbols:
        return {}
    today = dt.date.today()

    paid = db.execute(
        select(
            CorporateAction.symbol,
            func.sum(CorporateAction.value),
        )
        .where(
            CorporateAction.symbol.in_(symbols),
            CorporateAction.action_type == "dividend",
            CorporateAction.ex_date >= today - dt.timedelta(days=365),
            CorporateAction.ex_date <= today,
        )
        .group_by(CorporateAction.symbol)
    ).all()
    ttm = {symbol: float(total or 0.0) for symbol, total in paid}

    years = db.execute(
        select(
            CorporateAction.symbol,
            func.count(func.distinct(func.extract("year", CorporateAction.ex_date))),
        )
        .where(
            CorporateAction.symbol.in_(symbols),
            CorporateAction.action_type == "dividend",
            # Whole calendar years, so the window cannot straddle a sixth one
            # and report "6 of 5".
            func.extract("year", CorporateAction.ex_date) >= today.year - 5,
            func.extract("year", CorporateAction.ex_date) <= today.year - 1,
        )
        .group_by(CorporateAction.symbol)
    ).all()
    consistency = {symbol: min(int(count), 5) for symbol, count in years}

    close_rows = db.execute(
        select(DailyBar.symbol, DailyBar.close)
        .where(DailyBar.symbol.in_(symbols))
        .distinct(DailyBar.symbol)
        .order_by(DailyBar.symbol, DailyBar.date.desc())
    ).all()
    closes: dict[str, float] = {row[0]: float(row[1]) for row in close_rows}

    out: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        amount = ttm.get(symbol, 0.0)
        price = closes.get(symbol) or 0.0
        out[symbol] = {
            "dividend_ttm": round(amount, 2),
            "yield_pct": round(amount / price * 100, 2) if price and amount else 0.0,
            "years_paid_of_5": consistency.get(symbol, 0),
        }
    return out
