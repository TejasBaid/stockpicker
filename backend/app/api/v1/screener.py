"""Screener and factor-catalogue endpoints."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession
from app.factors.registry import all_factors, factors_by_category
from app.screener import service
from app.strategy.presets import PRESETS

router = APIRouter(prefix="/screener", tags=["screener"])


class FilterIn(BaseModel):
    factor: str
    op: Literal["gt", "gte", "lt", "lte"]
    value: float


class ScreenIn(BaseModel):
    weights: dict[str, float] = Field(default_factory=dict)
    universe: str = service.DEFAULT_UNIVERSE
    filters: list[FilterIn] = Field(default_factory=list)
    limit: int = Field(default=25, ge=1, le=200)
    max_per_sector: int | None = Field(default=None, ge=1, le=50)
    basis: Literal["zscore", "sector_zscore"] = "sector_zscore"
    as_of: dt.date | None = None


@router.get("/factors")
def factor_catalogue(user: CurrentUser) -> dict[str, Any]:
    """Everything the UI needs to render factor pickers and explanations."""
    return {
        "categories": {
            category: [
                {
                    "name": f.name,
                    "label": f.label,
                    "description": f.description,
                    "unit": f.unit,
                    "higher_is_better": f.higher_is_better,
                    "sector_neutral": f.sector_neutral,
                }
                for f in factors
            ]
            for category, factors in sorted(factors_by_category().items())
        },
        "count": len(all_factors()),
    }


@router.get("/presets")
def presets(user: CurrentUser) -> dict[str, Any]:
    return {
        "presets": [
            {
                "slug": slug,
                "name": preset["name"],
                "description": preset["description"],
                "weights": preset["weights"],
                "filters": preset.get("filters", []),
            }
            for slug, preset in PRESETS.items()
        ]
    }


@router.post("/run")
def run(payload: ScreenIn, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    request = service.ScreenRequest(
        weights=payload.weights,
        universe=payload.universe,
        filters=[service.Filter(f.factor, f.op, f.value) for f in payload.filters],
        limit=payload.limit,
        max_per_sector=payload.max_per_sector,
        basis=payload.basis,
        as_of=payload.as_of,
    )
    return service.run_screen(db, request)
