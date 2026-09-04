"""Backtest job worker.

Backtests rebuild a full point-in-time panel at every rebalance date, which is
far too heavy for a 512 MB web instance. The API enqueues a job and returns
immediately; this worker -- run on a GitHub Actions runner -- claims queued
jobs, runs them on real hardware and writes the result back.

    python -m app.backtest.worker --max-jobs 5

Claiming uses SELECT ... FOR UPDATE SKIP LOCKED so two runners can never take
the same job.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.engine import BacktestConfig, run_backtest
from app.db.models.research import BacktestJob
from app.db.session import session_scope
from app.screener.service import Filter, universe_members

log = structlog.get_logger(__name__)

# A job that has been "running" longer than this is assumed to have died with
# its runner, and is made available again.
STALE_AFTER = dt.timedelta(minutes=45)


def params_hash(params: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(params, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def claim_job(db: Session) -> BacktestJob | None:
    cutoff = dt.datetime.now(dt.UTC) - STALE_AFTER
    stale = db.scalars(
        select(BacktestJob).where(BacktestJob.status == "running", BacktestJob.claimed_at < cutoff)
    ).all()
    for dead in stale:
        dead.status = "queued"
        dead.claimed_at = None
        log.warning("backtest.job.requeued_stale", job=str(dead.id))
    if stale:
        db.commit()

    job = db.scalars(
        select(BacktestJob)
        .where(BacktestJob.status == "queued")
        .order_by(BacktestJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        return None
    job.status = "running"
    job.claimed_at = dt.datetime.now(dt.UTC)
    db.commit()
    return job


def config_from_params(db: Session, params: dict[str, Any]) -> BacktestConfig:
    symbols = params.get("symbols") or universe_members(db, params.get("universe", "nifty200"))
    return BacktestConfig(
        weights={k: float(v) for k, v in params["weights"].items()},
        start=dt.date.fromisoformat(params["start"]),
        end=dt.date.fromisoformat(params["end"]),
        universe_symbols=symbols,
        filters=[
            Filter(f["factor"], f["op"], float(f["value"])) for f in params.get("filters", [])
        ],
        holdings=int(params.get("holdings", 20)),
        frequency=params.get("frequency", "quarterly"),
        weighting=params.get("weighting", "equal"),
        max_per_sector=params.get("max_per_sector"),
        initial_capital=float(params.get("initial_capital", 1_000_000)),
    )


def run_job(db: Session, job: BacktestJob) -> None:
    started = time.monotonic()
    try:
        config = config_from_params(db, job.params)
        result = run_backtest(db, config)
        if "error" in result:
            job.status = "failed"
            job.error = result["error"]
        else:
            job.status = "done"
            job.result = result
            job.progress = 100
    except Exception as exc:
        db.rollback()
        job.status = "failed"
        job.error = str(exc)[:1000]
        log.error("backtest.job.failed", job=str(job.id), error=str(exc)[:300])
    finally:
        job.finished_at = dt.datetime.now(dt.UTC)
        db.commit()
        log.info(
            "backtest.job.finished",
            job=str(job.id),
            status=job.status,
            seconds=round(time.monotonic() - started, 1),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.backtest.worker")
    parser.add_argument("--max-jobs", type=int, default=5)
    args = parser.parse_args(argv)

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))

    processed = 0
    while processed < args.max_jobs:
        with session_scope() as db:
            job = claim_job(db)
            if job is None:
                break
            run_job(db, job)
        processed += 1

    print(f"Processed {processed} backtest job(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
