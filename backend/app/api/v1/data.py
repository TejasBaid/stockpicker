"""Data-health endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.services import data_health

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/overview")
def overview(db: DbSession, user: CurrentUser) -> dict[str, Any]:
    return data_health.overview(db)


@router.get("/runs")
def runs(db: DbSession, user: CurrentUser, limit: int = 30) -> list[dict[str, Any]]:
    return data_health.recent_runs(db, limit=min(limit, 100))
