"""Investment planning: turn an amount of money into an actionable buy list.

Four steps:

1. **How much to deploy.** The market regime suggests a percentage; the rest
   stays as dry powder, staged over a few tranches.
2. **What to buy.** The chosen strategy ranks the universe; the top names
   subject to a sector cap become the shortlist. Any name you swap out is
   replaced by the next-ranked candidate that still respects the cap.
3. **How much of each.** Equal weight, inverse-volatility, conviction-weighted
   or equal-risk sizing, converted to *whole shares* at the last close, with
   the rounding remainder returned to cash.
4. **What to watch.** An ATR-based stop for each position, plus a warning where
   a stock goes ex-dividend within days -- for an Indian taxable investor,
   buying just before an ex-date means paying for a dividend that is then taxed
   at your slab rate.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DataUnavailableError
from app.db.models.market import DailyBar, Instrument
from app.screener.service import Filter, ScreenRequest, run_screen, universe_members
from app.services import corporate_actions, regime
from app.services.portfolio import suggest_stop

Sizing = Literal["equal", "inverse_vol", "conviction", "equal_risk"]

# Below this a position is not worth the brokerage or the attention.
MIN_POSITION_VALUE = 5_000.0
# Cap any single name, however good it looks.
MAX_POSITION_WEIGHT = 0.20


@dataclass
class PlanRequest:
    capital: float
    weights: dict[str, float]
    filters: list[Filter] = field(default_factory=list)
    holdings: int = 15
    sizing: Sizing = "equal"
    max_per_sector: int | None = 4
    universe: str = "nifty200"
    excluded: list[str] = field(default_factory=list)
    stop_atr_multiple: float = 2.5
    override_deploy_pct: float | None = None


def _volatility(db: Session, symbols: list[str], days: int = 126) -> dict[str, float]:
    if not symbols:
        return {}
    start = dt.date.today() - dt.timedelta(days=int(days * 1.6))
    rows = db.execute(
        select(DailyBar.symbol, DailyBar.date, DailyBar.close)
        .where(DailyBar.symbol.in_(symbols), DailyBar.date >= start)
        .order_by(DailyBar.date)
    ).all()
    if not rows:
        return {}
    frame = pd.DataFrame(rows, columns=["symbol", "date", "close"])
    wide = frame.pivot_table(index="date", columns="symbol", values="close").ffill()
    vol = wide.pct_change(fill_method=None).std(ddof=0) * np.sqrt(252)
    return {s: float(v) for s, v in vol.items() if pd.notna(v) and v > 0}


def _target_weights(
    symbols: list[str],
    sizing: Sizing,
    scores: dict[str, float],
    vols: dict[str, float],
    stops: dict[str, dict[str, Any]],
) -> dict[str, float]:
    if not symbols:
        return {}

    if sizing == "equal":
        raw = dict.fromkeys(symbols, 1.0)
    elif sizing == "inverse_vol":
        median = float(np.median(list(vols.values()))) if vols else 0.25
        raw = {s: 1.0 / vols.get(s, median) for s in symbols}
    elif sizing == "conviction":
        # Shift the composite so the weakest included name still gets a
        # positive weight; a negative score must not become a short.
        floor = min(scores.get(s, 0.0) for s in symbols)
        shift = abs(floor) + 0.1 if floor <= 0 else 0.0
        raw = {s: scores.get(s, 0.0) + shift for s in symbols}
    else:  # equal_risk -- equal rupee loss if every stop is hit
        raw = {}
        for s in symbols:
            distance = stops.get(s, {}).get("stop_distance_pct")
            # Fall back to a nominal 10% risk when no stop could be computed.
            risk = abs(float(distance)) / 100.0 if distance else 0.10
            raw[s] = 1.0 / max(risk, 0.02)

    total = sum(raw.values()) or 1.0
    weights = {s: v / total for s, v in raw.items()}

    # With few enough names the cap is arithmetically unreachable: four
    # positions cannot each be held at 20% without leaving a fifth of the money
    # unallocated. Relax it to an equal share rather than silently under-deploy.
    cap = max(MAX_POSITION_WEIGHT, 1.0 / len(symbols))

    # Cap, then redistribute the excess across the names that still have room.
    for _ in range(20):
        excess = sum(max(0.0, w - cap) for w in weights.values())
        if excess < 1e-9:
            break
        weights = {s: min(w, cap) for s, w in weights.items()}
        headroom = {s: cap - w for s, w in weights.items() if w < cap - 1e-12}
        room = sum(headroom.values())
        if room < 1e-9:
            break
        for s, r in headroom.items():
            weights[s] += excess * (r / room)
    return weights


def build_plan(db: Session, request: PlanRequest) -> dict[str, Any]:
    if request.capital <= 0:
        raise DataUnavailableError("Enter an amount to invest.")

    symbols = universe_members(db, request.universe)
    conditions = regime.assess(db, symbols)

    deploy_pct = (
        request.override_deploy_pct
        if request.override_deploy_pct is not None
        else conditions.deploy_pct
    )
    deploy_pct = float(min(1.0, max(0.0, deploy_pct)))
    deployable = request.capital * deploy_pct

    # Rank deeper than needed so swaps and sector caps have somewhere to go.
    screen = run_screen(
        db,
        ScreenRequest(
            weights=request.weights,
            filters=request.filters,
            universe=request.universe,
            limit=max(request.holdings * 3, 40),
            max_per_sector=None,  # the cap is applied during selection below
            basis="sector_zscore",
        ),
    )
    ranked = [r for r in screen["results"] if r["symbol"] not in set(request.excluded)]
    if not ranked:
        raise DataUnavailableError("No candidates survived the filters and exclusions.")

    selected: list[dict[str, Any]] = []
    per_sector: dict[str, int] = {}
    for row in ranked:
        sector = row.get("sector") or "Unknown"
        if (
            request.max_per_sector is not None
            and per_sector.get(sector, 0) >= request.max_per_sector
        ):
            continue
        selected.append(row)
        per_sector[sector] = per_sector.get(sector, 0) + 1
        if len(selected) >= request.holdings:
            break

    chosen = [r["symbol"] for r in selected]
    scores = {r["symbol"]: float(r["composite"]) for r in ranked}
    vols = _volatility(db, chosen)
    stops = {s: suggest_stop(db, s, multiple=request.stop_atr_multiple) for s in chosen}
    weights = _target_weights(chosen, request.sizing, scores, vols, stops)

    prices = {s: stops[s].get("price") for s in chosen}
    events = corporate_actions.upcoming(db, chosen, within_days=45)
    dividends = corporate_actions.trailing_dividends(db, chosen)
    meta = {r["symbol"]: r for r in selected}

    # Drop what cannot be bought, then renormalise the weights across what is
    # left. Without this, a single share priced above its own slice (Page
    # Industries at 36,000 a share) silently parks its whole allocation in cash.
    skipped: list[dict[str, Any]] = []
    affordable: list[str] = []
    for symbol in chosen:
        price = prices.get(symbol)
        if not price or price <= 0:
            skipped.append({"symbol": symbol, "reason": "no recent price"})
            continue
        slice_value = deployable * weights.get(symbol, 0.0)
        if price > slice_value:
            skipped.append(
                {
                    "symbol": symbol,
                    "reason": (
                        f"one share costs {price:,.0f}, more than the "
                        f"{slice_value:,.0f} this position was allotted"
                    ),
                }
            )
            continue
        if slice_value < MIN_POSITION_VALUE:
            skipped.append(
                {
                    "symbol": symbol,
                    "reason": (
                        f"only {slice_value:,.0f} would be committed, below the "
                        f"{MIN_POSITION_VALUE:,.0f} minimum worth holding"
                    ),
                }
            )
            continue
        affordable.append(symbol)

    if affordable:
        remaining = sum(weights.get(s, 0.0) for s in affordable) or 1.0
        weights = {s: weights.get(s, 0.0) / remaining for s in affordable}

    allocations: list[dict[str, Any]] = []
    invested = 0.0

    for symbol in affordable:
        price = prices[symbol] or 0.0
        target_value = deployable * weights.get(symbol, 0.0)
        shares = math.floor(target_value / price)
        if shares <= 0:
            continue
        value = shares * price
        invested += value
        row = meta[symbol]
        stop = stops[symbol]
        upcoming_events = events.get(symbol, [])
        imminent = [e for e in upcoming_events if e["imminent"]]

        allocations.append(
            {
                "symbol": symbol,
                "name": row.get("name"),
                "sector": row.get("sector"),
                "rank": row.get("rank"),
                "score": round(float(row["composite"]), 3),
                "price": round(price, 2),
                "shares": shares,
                "value": round(value, 2),
                "target_weight_pct": round(weights.get(symbol, 0.0) * 100, 2),
                "volatility_pct": round(vols.get(symbol, 0.0) * 100, 1) if symbol in vols else None,
                "stop": stop.get("stop"),
                "stop_distance_pct": stop.get("stop_distance_pct"),
                "risk_amount": (
                    round(value * abs(stop["stop_distance_pct"]) / 100, 2)
                    if stop.get("stop_distance_pct")
                    else None
                ),
                "dividend": dividends.get(symbol),
                "corporate_actions": upcoming_events,
                "warning": (
                    f"Goes ex-dividend on {imminent[0]['ex_date']} "
                    f"({imminent[0]['days_away']} days) — the price drops by roughly the "
                    f"dividend and the payout is taxed at your slab rate, so buying after "
                    f"the ex-date is usually cleaner."
                    if imminent
                    else None
                ),
                "factors": row.get("factors", {}),
            }
        )

    # Whole-share rounding, plus any name skipped for being unaffordable,
    # leaves cash idle. Spend it down by topping up the position that is
    # furthest below its target weight and can still afford another share --
    # otherwise a single expensive stock silently parks a tenth of the money.
    if allocations:
        leftover = deployable - invested
        for _ in range(200):
            candidates = [
                a
                for a in allocations
                if a["price"] <= leftover
                and (a["value"] + a["price"]) / deployable <= MAX_POSITION_WEIGHT
            ]
            if not candidates:
                break
            # Furthest below target, measured in rupees still owed.
            target = max(
                candidates,
                key=lambda a: deployable * a["target_weight_pct"] / 100 - a["value"],
            )
            shortfall = deployable * target["target_weight_pct"] / 100 - target["value"]
            if shortfall < target["price"] * 0.5:
                break
            target["shares"] += 1
            target["value"] = round(target["value"] + target["price"], 2)
            leftover -= target["price"]
            invested += target["price"]

        for a in allocations:
            a["actual_weight_pct"] = round(a["value"] / invested * 100, 2) if invested else 0.0
            if a["stop_distance_pct"]:
                a["risk_amount"] = round(a["value"] * abs(a["stop_distance_pct"]) / 100, 2)

    # Anything ranked but not selected is a swap candidate.
    alternates = [
        {
            "symbol": r["symbol"],
            "name": r.get("name"),
            "sector": r.get("sector"),
            "rank": r.get("rank"),
            "score": round(float(r["composite"]), 3),
            "price": None,
        }
        for r in ranked
        if r["symbol"] not in set(chosen)
    ][:25]

    cash_reserve = request.capital - deployable
    rounding_cash = max(0.0, deployable - invested)
    total_risk = sum(a["risk_amount"] or 0.0 for a in allocations)

    sector_exposure: dict[str, float] = {}
    for a in allocations:
        sector_exposure[a["sector"] or "Unknown"] = (
            sector_exposure.get(a["sector"] or "Unknown", 0.0) + a["value"]
        )

    return {
        "as_of": screen["as_of"],
        "capital": request.capital,
        "regime": {
            "state": conditions.state,
            "score": conditions.score,
            "suggested_deploy_pct": conditions.deploy_pct * 100,
            "signals": conditions.signals,
            "note": conditions.note,
            "as_of": conditions.as_of.isoformat(),
        },
        "deploy_pct": round(deploy_pct * 100, 1),
        "deployable": round(deployable, 2),
        "invested": round(invested, 2),
        "cash_reserve": round(cash_reserve, 2),
        "uninvested_cash": round(rounding_cash, 2),
        "tranches": conditions.tranches,
        "sizing": request.sizing,
        "positions": len(allocations),
        "allocations": allocations,
        "alternates": alternates,
        "skipped": skipped,
        "total_risk_amount": round(total_risk, 2),
        "total_risk_pct": round(total_risk / request.capital * 100, 2) if request.capital else 0.0,
        "sector_exposure": [
            {"sector": k, "value": round(v, 2), "pct": round(v / invested * 100, 1)}
            for k, v in sorted(sector_exposure.items(), key=lambda kv: -kv[1])
        ]
        if invested
        else [],
    }


def swap(db: Session, request: PlanRequest, drop: str, add: str | None = None) -> dict[str, Any]:
    """Replace a suggested name.

    Without a replacement the dropped name is simply excluded and the next
    candidate takes its place; with one, that specific stock is pinned in.
    """
    excluded = [*request.excluded, drop]
    if add is None:
        return build_plan(db, PlanRequest(**{**request.__dict__, "excluded": excluded}))

    add = add.strip().upper()
    if db.get(Instrument, add) is None:
        raise DataUnavailableError(f"{add} is not in the instrument master.")

    plan = build_plan(db, PlanRequest(**{**request.__dict__, "excluded": excluded}))
    if any(a["symbol"] == add for a in plan["allocations"]):
        return plan

    # The requested name did not make the cut on its own, so pin it by dropping
    # the weakest selected name in its place.
    weakest = (
        min(plan["allocations"], key=lambda a: a["score"])["symbol"]
        if plan["allocations"]
        else None
    )
    if weakest is None:
        return plan
    forced = build_plan(
        db,
        PlanRequest(
            **{
                **request.__dict__,
                "excluded": [*excluded, weakest],
                "holdings": request.holdings - 1,
            }
        ),
    )
    forced["pinned"] = add
    return forced
