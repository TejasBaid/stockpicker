"""Portfolio endpoints.

Positions are entered by hand. Nothing here reads the brokerage account.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import AppError, NotFoundError
from app.db.models.market import Instrument
from app.db.models.portfolio import Portfolio, Position, Trade
from app.services import portfolio as service

router = APIRouter(prefix="/portfolios", tags=["portfolio"])


class PortfolioIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    cash: float = Field(default=0.0, ge=0)


class PositionIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    quantity: float = Field(gt=0)
    avg_price: float = Field(gt=0)
    opened_on: dt.date
    thesis: str | None = None
    conviction: str | None = Field(default=None, max_length=20)


class ExitPlanIn(BaseModel):
    stop_type: str | None = Field(default=None, max_length=20)
    stop_value: float | None = None
    stop_price: float | None = None
    target_ladder: list[dict[str, Any]] | None = None
    time_stop_on: dt.date | None = None
    factor_decay_rules: dict[str, Any] | None = None
    notes: str | None = None


class TradeIn(BaseModel):
    side: str = Field(pattern="^(BUY|SELL)$")
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    traded_on: dt.date
    fees: float = Field(default=0.0, ge=0)
    notes: str | None = None


def _ident(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise AppError("Invalid id.") from exc


@router.get("")
def list_portfolios(db: DbSession, user: CurrentUser) -> list[dict[str, Any]]:
    return service.list_portfolios(db, user.id)


@router.post("", status_code=201)
def create_portfolio(payload: PortfolioIn, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    portfolio = Portfolio(
        owner_id=user.id,
        name=payload.name,
        description=payload.description,
        cash=Decimal(str(payload.cash)),
    )
    db.add(portfolio)
    db.commit()
    return service.summarise(db, portfolio)


@router.get("/{portfolio_id}")
def get_portfolio(portfolio_id: str, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    portfolio = service.get_portfolio(db, _ident(portfolio_id), user.id)
    return {
        **service.summarise(db, portfolio),
        "holdings": service.position_detail(db, portfolio),
        "tax": service.realised_gains(db, portfolio),
    }


@router.post("/{portfolio_id}/positions", status_code=201)
def add_position(
    portfolio_id: str, payload: PositionIn, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    portfolio = service.get_portfolio(db, _ident(portfolio_id), user.id)
    symbol = payload.symbol.strip().upper()
    if db.get(Instrument, symbol) is None:
        raise NotFoundError(f"{symbol} is not in the instrument master.")

    position = Position(
        portfolio_id=portfolio.id,
        symbol=symbol,
        quantity=Decimal(str(payload.quantity)),
        avg_price=Decimal(str(payload.avg_price)),
        opened_on=payload.opened_on,
        thesis=payload.thesis,
        conviction=payload.conviction,
        # Snapshot the factor ranks now, so decay can be measured against them.
        entry_factors=service.capture_entry_factors(db, symbol),
    )
    db.add(position)
    db.flush()
    db.add(
        Trade(
            position_id=position.id,
            side="BUY",
            quantity=position.quantity,
            price=position.avg_price,
            traded_on=payload.opened_on,
        )
    )
    db.commit()
    return {"id": str(position.id), "symbol": symbol}


@router.delete("/{portfolio_id}/positions/{position_id}", status_code=204)
def remove_position(portfolio_id: str, position_id: str, db: DbSession, user: CurrentUser) -> None:
    portfolio = service.get_portfolio(db, _ident(portfolio_id), user.id)
    position = db.get(Position, _ident(position_id))
    if position is None or position.portfolio_id != portfolio.id:
        raise NotFoundError("Position not found.")
    db.delete(position)
    db.commit()


@router.post("/{portfolio_id}/positions/{position_id}/trades", status_code=201)
def add_trade(
    portfolio_id: str, position_id: str, payload: TradeIn, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    portfolio = service.get_portfolio(db, _ident(portfolio_id), user.id)
    position = db.get(Position, _ident(position_id))
    if position is None or position.portfolio_id != portfolio.id:
        raise NotFoundError("Position not found.")

    quantity = Decimal(str(payload.quantity))
    price = Decimal(str(payload.price))
    db.add(
        Trade(
            position_id=position.id,
            side=payload.side,
            quantity=quantity,
            price=price,
            traded_on=payload.traded_on,
            fees=Decimal(str(payload.fees)),
            notes=payload.notes,
        )
    )

    if payload.side == "BUY":
        total_cost = position.quantity * position.avg_price + quantity * price
        position.quantity += quantity
        position.avg_price = total_cost / position.quantity
    else:
        position.quantity -= quantity
        if position.quantity <= 0:
            position.quantity = Decimal("0")
            position.closed_on = payload.traded_on

    db.commit()
    return {"quantity": float(position.quantity), "avg_price": float(position.avg_price)}


@router.put("/{portfolio_id}/positions/{position_id}/exit-plan")
def set_exit_plan(
    portfolio_id: str, position_id: str, payload: ExitPlanIn, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    portfolio = service.get_portfolio(db, _ident(portfolio_id), user.id)
    position = db.get(Position, _ident(position_id))
    if position is None or position.portfolio_id != portfolio.id:
        raise NotFoundError("Position not found.")

    service.create_exit_plan(db, position, **payload.model_dump())
    db.refresh(position)
    return {"ok": True}


@router.get("/{portfolio_id}/stop-suggestion/{symbol}")
def stop_suggestion(
    portfolio_id: str, symbol: str, db: DbSession, user: CurrentUser, multiple: float = 2.5
) -> dict[str, Any]:
    service.get_portfolio(db, _ident(portfolio_id), user.id)
    return service.suggest_stop(db, symbol.upper(), multiple=multiple)


@router.post("/{portfolio_id}/rebalance")
def rebalance(
    portfolio_id: str, targets: dict[str, float], db: DbSession, user: CurrentUser
) -> list[dict[str, Any]]:
    portfolio = service.get_portfolio(db, _ident(portfolio_id), user.id)
    return service.rebalance_proposal(db, portfolio, targets)


@router.get("/{portfolio_id}/alerts")
def alerts(portfolio_id: str, db: DbSession, user: CurrentUser) -> list[dict[str, Any]]:
    """Everything that needs attention: stops hit, targets reached, factor decay."""
    portfolio = service.get_portfolio(db, _ident(portfolio_id), user.id)
    out: list[dict[str, Any]] = []
    for holding in service.position_detail(db, portfolio):
        plan = holding.get("exit_plan") or {}
        for trigger in plan.get("triggers", []):
            out.append({"symbol": holding["symbol"], "kind": "exit", "message": trigger})
        for drift in holding.get("factor_drift", []):
            if drift["drift"] >= 4:
                out.append(
                    {
                        "symbol": holding["symbol"],
                        "kind": "factor_decay",
                        "message": (
                            f"{drift['factor']} has fallen from decile "
                            f"{drift['entry_decile']} to {drift['current_decile']} since entry"
                        ),
                    }
                )
        if holding["days_to_long_term"] in range(1, 31):
            out.append(
                {
                    "symbol": holding["symbol"],
                    "kind": "tax",
                    "message": (
                        f"{holding['days_to_long_term']} days until this qualifies for "
                        "long-term capital gains treatment"
                    ),
                }
            )
    return out


@router.get("/_search/instruments")
def search_instruments(q: str, db: DbSession, user: CurrentUser) -> list[dict[str, str]]:
    term = f"%{q.strip().upper()}%"
    rows = db.execute(
        select(Instrument.symbol, Instrument.name)
        .where(Instrument.symbol.ilike(term) | Instrument.name.ilike(f"%{q.strip()}%"))
        .order_by(Instrument.symbol)
        .limit(15)
    ).all()
    return [{"symbol": s, "name": n} for s, n in rows]
