"""Investment planning endpoints."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import NotFoundError
from app.db.models.research import Strategy
from app.factors.registry import all_factors
from app.screener.service import Filter, universe_members
from app.services import regime
from app.services.plan import PlanRequest, build_plan, swap
from app.strategy.presets import PRESETS

router = APIRouter(prefix="/plan", tags=["plan"])


class FilterIn(BaseModel):
    factor: str
    op: Literal["gt", "gte", "lt", "lte"]
    value: float


class PlanIn(BaseModel):
    capital: float = Field(gt=0, le=1e11)
    # Either a preset/saved strategy, or an explicit weighting.
    strategy: str | None = None
    weights: dict[str, float] | None = None
    filters: list[FilterIn] | None = None
    holdings: int = Field(default=15, ge=3, le=50)
    sizing: Literal["equal", "inverse_vol", "conviction", "equal_risk"] = "equal"
    max_per_sector: int | None = Field(default=4, ge=1, le=50)
    excluded: list[str] = Field(default_factory=list)
    stop_atr_multiple: float = Field(default=2.5, ge=0.5, le=10)
    override_deploy_pct: float | None = Field(default=None, ge=0, le=100)
    # Swap controls
    drop: str | None = None
    add: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> PlanIn:
        if not self.strategy and not self.weights:
            raise ValueError("Choose a strategy or provide factor weights.")
        if self.weights:
            unknown = sorted(set(self.weights) - set(all_factors()))
            if unknown:
                raise ValueError(f"Unknown factor(s): {', '.join(unknown)}")
        return self


def _resolve(db: DbSession, payload: PlanIn, user_id: Any) -> tuple[dict[str, float], list[Filter]]:
    if payload.weights:
        filters = [Filter(f.factor, f.op, f.value) for f in (payload.filters or [])]
        return payload.weights, filters

    slug = payload.strategy or ""
    if slug in PRESETS:
        preset = PRESETS[slug]
        return preset["weights"], [Filter(**f) for f in preset.get("filters", [])]

    saved = db.scalars(
        select(Strategy)
        .where(Strategy.owner_id == user_id, Strategy.slug == slug, Strategy.archived.is_(False))
        .order_by(Strategy.version.desc())
        .limit(1)
    ).first()
    if saved is None:
        raise NotFoundError(f"No strategy called '{slug}'.")
    definition = saved.definition or {}
    return (
        definition.get("weights", {}),
        [Filter(**f) for f in definition.get("filters", [])],
    )


@router.get("/regime")
def market_regime(db: DbSession, user: CurrentUser) -> dict[str, Any]:
    """Market conditions and the deployment they suggest."""
    conditions = regime.assess(db, universe_members(db, "nifty200"))
    return {
        "state": conditions.state,
        "score": conditions.score,
        "deploy_pct": conditions.deploy_pct * 100,
        "signals": conditions.signals,
        "tranches": conditions.tranches,
        "note": conditions.note,
        "as_of": conditions.as_of.isoformat(),
    }


@router.post("")
def create_plan(payload: PlanIn, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    weights, filters = _resolve(db, payload, user.id)
    request = PlanRequest(
        capital=payload.capital,
        weights=weights,
        filters=filters,
        holdings=payload.holdings,
        sizing=payload.sizing,
        max_per_sector=payload.max_per_sector,
        excluded=[s.strip().upper() for s in payload.excluded],
        stop_atr_multiple=payload.stop_atr_multiple,
        override_deploy_pct=(
            payload.override_deploy_pct / 100 if payload.override_deploy_pct is not None else None
        ),
    )
    if payload.drop:
        return swap(db, request, payload.drop.strip().upper(), payload.add)
    return build_plan(db, request)
