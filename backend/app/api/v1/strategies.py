"""Saved strategies and watchlists.

A strategy is a named weighting over registered factors plus optional gates.
Saving one bumps its version rather than overwriting, so a backtest result
always refers to the exact definition that produced it.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.models.factors import FactorValue
from app.db.models.market import Instrument
from app.db.models.portfolio import Watchlist, WatchlistItem
from app.db.models.research import Strategy
from app.factors.registry import all_factors

router = APIRouter(tags=["strategies"])

SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    return SLUG_RE.sub("-", name.strip().lower()).strip("-")[:80] or "strategy"


class FilterIn(BaseModel):
    factor: str
    op: Literal["gt", "gte", "lt", "lte"]
    value: float


class StrategyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    weights: dict[str, float]
    filters: list[FilterIn] = Field(default_factory=list)
    max_per_sector: int | None = Field(default=4, ge=1, le=50)
    limit: int = Field(default=25, ge=1, le=200)

    @model_validator(mode="after")
    def _validate(self) -> StrategyIn:
        if not self.weights:
            raise ValueError("Provide at least one factor weight.")
        known = set(all_factors())
        unknown = sorted((set(self.weights) | {f.factor for f in self.filters}) - known)
        if unknown:
            raise ValueError(f"Unknown factor(s): {', '.join(unknown)}")
        return self


def _serialise(strategy: Strategy) -> dict[str, Any]:
    definition = strategy.definition or {}
    return {
        "id": str(strategy.id),
        "slug": strategy.slug,
        "name": strategy.name,
        "description": strategy.description,
        "version": strategy.version,
        "weights": definition.get("weights", {}),
        "filters": definition.get("filters", []),
        "max_per_sector": definition.get("max_per_sector"),
        "limit": definition.get("limit", 25),
        "created_at": strategy.created_at.isoformat(),
        "updated_at": strategy.updated_at.isoformat(),
    }


@router.get("/strategies")
def list_strategies(db: DbSession, user: CurrentUser) -> list[dict[str, Any]]:
    """Latest version of each of the user's strategies."""
    rows = db.scalars(
        select(Strategy)
        .where(Strategy.owner_id == user.id, Strategy.archived.is_(False))
        .order_by(Strategy.slug, Strategy.version.desc())
    ).all()
    latest: dict[str, Strategy] = {}
    for s in rows:
        latest.setdefault(s.slug, s)
    return [
        _serialise(s) for s in sorted(latest.values(), key=lambda s: s.updated_at, reverse=True)
    ]


@router.post("/strategies", status_code=201)
def save_strategy(payload: StrategyIn, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    slug = _slugify(payload.name)
    current = db.scalar(
        select(func.max(Strategy.version)).where(
            Strategy.owner_id == user.id, Strategy.slug == slug
        )
    )
    strategy = Strategy(
        owner_id=user.id,
        slug=slug,
        name=payload.name,
        description=payload.description,
        version=(current or 0) + 1,
        definition={
            "weights": payload.weights,
            "filters": [f.model_dump() for f in payload.filters],
            "max_per_sector": payload.max_per_sector,
            "limit": payload.limit,
        },
    )
    db.add(strategy)
    db.commit()
    return _serialise(strategy)


@router.delete("/strategies/{strategy_id}", status_code=204)
def archive_strategy(strategy_id: str, db: DbSession, user: CurrentUser) -> None:
    try:
        ident = uuid.UUID(strategy_id)
    except ValueError as exc:
        raise AppError("Invalid strategy id.") from exc
    strategy = db.get(Strategy, ident)
    if strategy is None or strategy.owner_id != user.id:
        raise NotFoundError("Strategy not found.")
    # Archive every version of the slug, so it disappears as one thing.
    for version in db.scalars(
        select(Strategy).where(Strategy.owner_id == user.id, Strategy.slug == strategy.slug)
    ).all():
        version.archived = True
    db.commit()


# --- watchlists ------------------------------------------------------------


class WatchlistItemIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    note: str | None = None


def _default_watchlist(db: DbSession, user_id: uuid.UUID) -> Watchlist:
    watchlist = db.scalar(select(Watchlist).where(Watchlist.owner_id == user_id).limit(1))
    if watchlist is None:
        watchlist = Watchlist(owner_id=user_id, name="Watchlist")
        db.add(watchlist)
        db.commit()
    return watchlist


@router.get("/watchlist")
def get_watchlist(db: DbSession, user: CurrentUser) -> dict[str, Any]:
    """Watched names with their current factor standing."""
    watchlist = _default_watchlist(db, user.id)
    symbols = [item.symbol for item in watchlist.items]
    if not symbols:
        return {"id": str(watchlist.id), "items": []}

    meta = {
        row[0]: {"name": row[1], "sector": row[2]}
        for row in db.execute(
            select(Instrument.symbol, Instrument.name, Instrument.sector).where(
                Instrument.symbol.in_(symbols)
            )
        ).all()
    }

    as_of = db.scalar(select(func.max(FactorValue.as_of)))
    highlights = ("roce", "earnings_yield", "momentum_12_1", "rating_revision")
    ranks: dict[str, dict[str, int | None]] = {s: {} for s in symbols}
    if as_of is not None:
        for symbol, factor, decile in db.execute(
            select(FactorValue.symbol, FactorValue.factor, FactorValue.decile).where(
                FactorValue.as_of == as_of,
                FactorValue.symbol.in_(symbols),
                FactorValue.factor.in_(highlights),
            )
        ).all():
            ranks[symbol][factor] = decile

    return {
        "id": str(watchlist.id),
        "as_of": as_of.isoformat() if as_of else None,
        "factors": list(highlights),
        "items": [
            {
                "symbol": item.symbol,
                "name": meta.get(item.symbol, {}).get("name"),
                "sector": meta.get(item.symbol, {}).get("sector"),
                "note": item.note,
                "deciles": ranks.get(item.symbol, {}),
            }
            for item in sorted(watchlist.items, key=lambda i: i.symbol)
        ],
    }


@router.post("/watchlist/items", status_code=201)
def add_watchlist_item(
    payload: WatchlistItemIn, db: DbSession, user: CurrentUser
) -> dict[str, str]:
    watchlist = _default_watchlist(db, user.id)
    symbol = payload.symbol.strip().upper()
    if db.get(Instrument, symbol) is None:
        raise NotFoundError(f"{symbol} is not in the instrument master.")
    if any(i.symbol == symbol for i in watchlist.items):
        raise ConflictError(f"{symbol} is already on the watchlist.")
    db.add(WatchlistItem(watchlist_id=watchlist.id, symbol=symbol, note=payload.note))
    db.commit()
    return {"symbol": symbol}


@router.delete("/watchlist/items/{symbol}", status_code=204)
def remove_watchlist_item(symbol: str, db: DbSession, user: CurrentUser) -> None:
    watchlist = _default_watchlist(db, user.id)
    item = next((i for i in watchlist.items if i.symbol == symbol.upper()), None)
    if item is None:
        raise NotFoundError("Not on the watchlist.")
    db.delete(item)
    db.commit()
