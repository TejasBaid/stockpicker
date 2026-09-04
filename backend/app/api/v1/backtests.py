"""Backtest endpoints.

The API only enqueues. Running a backtest rebuilds a point-in-time panel at
every rebalance date, which would exhaust the web instance; a GitHub Actions
worker does the work and writes results back. The UI polls.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.backtest.worker import params_hash
from app.core.errors import AppError, NotFoundError
from app.db.models.research import BacktestJob
from app.factors.registry import all_factors

router = APIRouter(prefix="/backtests", tags=["backtests"])

MIN_PERIOD_DAYS = 180


class BacktestIn(BaseModel):
    weights: dict[str, float]
    start: dt.date
    end: dt.date
    universe: str = "nifty200"
    filters: list[dict[str, Any]] = Field(default_factory=list)
    holdings: int = Field(default=20, ge=3, le=100)
    frequency: Literal["monthly", "quarterly", "yearly"] = "quarterly"
    weighting: Literal["equal", "inverse_vol"] = "equal"
    max_per_sector: int | None = Field(default=4, ge=1, le=50)
    initial_capital: float = Field(default=1_000_000, gt=0)

    @model_validator(mode="after")
    def _validate(self) -> BacktestIn:
        if not self.weights:
            raise ValueError("Provide at least one factor weight.")
        unknown = sorted(set(self.weights) - set(all_factors()))
        if unknown:
            raise ValueError(f"Unknown factor(s): {', '.join(unknown)}")
        if (self.end - self.start).days < MIN_PERIOD_DAYS:
            raise ValueError("The period must be at least six months.")
        if self.end > dt.date.today():
            raise ValueError("The end date cannot be in the future.")
        return self


def _serialise(job: BacktestJob, *, include_result: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(job.id),
        "status": job.status,
        "progress": job.progress,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "params": job.params,
    }
    if include_result:
        out["result"] = job.result
    return out


@router.post("", status_code=202)
def enqueue(payload: BacktestIn, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    params = payload.model_dump(mode="json")
    digest = params_hash(params)

    # An identical backtest that already succeeded is returned immediately
    # rather than recomputed -- the inputs are deterministic.
    existing = db.scalars(
        select(BacktestJob)
        .where(
            BacktestJob.owner_id == user.id,
            BacktestJob.params_hash == digest,
            BacktestJob.status.in_(("done", "queued", "running")),
        )
        .order_by(BacktestJob.created_at.desc())
        .limit(1)
    ).first()
    if existing is not None:
        return _serialise(existing)

    job = BacktestJob(owner_id=user.id, params_hash=digest, params=params, status="queued")
    db.add(job)
    db.commit()
    return _serialise(job)


@router.get("")
def list_jobs(db: DbSession, user: CurrentUser, limit: int = 20) -> list[dict[str, Any]]:
    jobs = db.scalars(
        select(BacktestJob)
        .where(BacktestJob.owner_id == user.id)
        .order_by(BacktestJob.created_at.desc())
        .limit(min(limit, 100))
    ).all()
    return [_serialise(j, include_result=False) for j in jobs]


@router.get("/{job_id}")
def get_job(job_id: str, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    try:
        ident = uuid.UUID(job_id)
    except ValueError as exc:
        raise AppError("Invalid backtest id.") from exc
    job = db.get(BacktestJob, ident)
    if job is None or job.owner_id != user.id:
        raise NotFoundError("Backtest not found.")
    return _serialise(job)
