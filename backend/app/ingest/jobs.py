"""Ingest orchestration -- the entrypoint GitHub Actions runs nightly.

    python -m app.ingest.jobs nightly

Render's free tier has no cron jobs or background workers, so this runs on a
GitHub Actions runner instead. That also means real CPU and memory rather than
a 512 MB / 0.1 CPU instance, and it does not require the web service to be
awake.

Quota is the binding constraint on the fundamentals side: the vendor publishes
no limits, so the expensive jobs are *staggered* -- each nightly run refreshes
one slice of the universe, cycling through it over the course of a week rather
than spending a week's budget in one night.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from collections.abc import Callable
from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.ops import IngestRun
from app.db.session import session_scope
from app.ingest import bars, estimates, fundamentals, instruments, valuation
from app.providers.groww import GrowwClient
from app.providers.indian_api import IndianApiClient

log = structlog.get_logger(__name__)
settings = get_settings()

# Spread the universe across the week so no single night is expensive.
FUNDAMENTALS_SLICES = 7
ESTIMATES_SLICES = 7
VALUATION_SLICES = 28  # monthly cadence; multiples move slowly


def _slice_for_today(symbols: list[str], slices: int, *, today: dt.date | None = None) -> list[str]:
    """Deterministic slice of the universe for today, so every symbol is
    refreshed exactly once per cycle without tracking state."""
    today = today or dt.date.today()
    index = today.toordinal() % slices
    return [s for i, s in enumerate(sorted(symbols)) if i % slices == index]


class RunRecorder:
    """Records each job in ``ingest_runs`` so the data-health page can show what
    ran, how long it took, and what failed."""

    def __init__(self, db: Session, job: str) -> None:
        self.db = db
        self.run = IngestRun(job=job, status="running", started_at=dt.datetime.now(dt.UTC))
        db.add(self.run)
        db.commit()
        self._start = time.monotonic()

    def finish(self, status: str = "ok", **details: Any) -> None:
        self.run.status = status
        self.run.finished_at = dt.datetime.now(dt.UTC)
        self.run.duration_seconds = round(time.monotonic() - self._start, 2)
        self.run.rows_written = int(details.pop("rows", 0) or 0)
        self.run.symbols_processed = int(details.pop("processed", 0) or 0)
        self.run.symbols_failed = int(details.pop("failed", 0) or 0)
        self.run.api_calls = int(details.pop("api_calls", 0) or 0)
        self.run.error = details.pop("error", None)
        self.run.details = dict(details)
        self.db.commit()


# --- individual jobs -------------------------------------------------------


def job_instruments(db: Session) -> dict[str, Any]:
    rec = RunRecorder(db, "instruments")
    try:
        count = instruments.sync_instrument_master(db)
        seeded, missing = instruments.seed_nifty200(db)
        rec.finish(rows=count, processed=seeded, missing_from_master=missing)
        return {"instruments": count, "universe": seeded, "missing": missing}
    except Exception as exc:
        rec.finish("failed", error=str(exc)[:500])
        raise


def job_bars(db: Session, symbols: list[str]) -> dict[str, Any]:
    rec = RunRecorder(db, "bars")
    try:
        client = GrowwClient()
        # The benchmark needs bars too, but may already be in the universe list.
        targets = list(dict.fromkeys([*symbols, instruments.BENCHMARK_SYMBOL]))
        rows, processed, failed = bars.ingest_bars(db, targets, client=client)
        rec.finish(rows=rows, processed=processed, failed=len(failed), failed_symbols=failed[:50])
        return {"rows": rows, "processed": processed, "failed": failed}
    except Exception as exc:
        rec.finish("failed", error=str(exc)[:500])
        raise


def job_fundamentals(db: Session, symbols: list[str], *, full: bool = False) -> dict[str, Any]:
    rec = RunRecorder(db, "fundamentals")
    targets = symbols if full else _slice_for_today(symbols, FUNDAMENTALS_SLICES)
    try:
        with IndianApiClient(db) as client:
            rows, failed, uncovered = fundamentals.ingest_fundamentals(db, client, targets)
            used = client.budget.used_today()
        rec.finish(
            rows=rows,
            processed=len(targets),
            failed=len(failed),
            api_calls=used,
            uncovered=uncovered[:50],
            failed_symbols=failed[:50],
        )
        return {"rows": rows, "processed": len(targets), "failed": failed, "uncovered": uncovered}
    except Exception as exc:
        rec.finish("failed", error=str(exc)[:500])
        raise


def job_estimates(db: Session, symbols: list[str], *, full: bool = False) -> dict[str, Any]:
    rec = RunRecorder(db, "estimates")
    targets = symbols if full else _slice_for_today(symbols, ESTIMATES_SLICES)
    try:
        with IndianApiClient(db) as client:
            rows, failed = estimates.ingest_estimates(db, client, targets)
            used = client.budget.used_today()
        rec.finish(rows=rows, processed=len(targets), failed=len(failed), api_calls=used)
        return {"rows": rows, "processed": len(targets), "failed": failed}
    except Exception as exc:
        rec.finish("failed", error=str(exc)[:500])
        raise


def job_valuation(db: Session, symbols: list[str], *, full: bool = False) -> dict[str, Any]:
    rec = RunRecorder(db, "valuation")
    targets = symbols if full else _slice_for_today(symbols, VALUATION_SLICES)
    try:
        with IndianApiClient(db) as client:
            rows, failed = valuation.ingest_valuation_history(db, client, targets)
            used = client.budget.used_today()
        rec.finish(rows=rows, processed=len(targets), failed=len(failed), api_calls=used)
        return {"rows": rows, "processed": len(targets), "failed": failed}
    except Exception as exc:
        rec.finish("failed", error=str(exc)[:500])
        raise


def job_factors(db: Session, symbols: list[str]) -> dict[str, Any]:
    """Precompute factor values. Phase 2 fills this in; the nightly job already
    calls it so the wiring is proven before the maths lands."""
    from app.factors.precompute import precompute_factors

    rec = RunRecorder(db, "factors")
    try:
        result = precompute_factors(db, symbols)
        details = {k: v for k, v in result.items() if k not in {"rows", "symbols"}}
        rec.finish(rows=result.get("rows", 0), processed=len(symbols), **details)
        return result
    except Exception as exc:
        rec.finish("failed", error=str(exc)[:500])
        raise


def job_nightly(db: Session, symbols: list[str]) -> dict[str, Any]:
    """The scheduled run. Estimates go first: they carry the real earnings
    announcement dates that fundamentals then use to date ``known_on``."""
    out: dict[str, Any] = {}
    for name, fn in (
        ("instruments", lambda: job_instruments(db)),
        ("bars", lambda: job_bars(db, symbols)),
        ("estimates", lambda: job_estimates(db, symbols)),
        ("fundamentals", lambda: job_fundamentals(db, symbols)),
        ("valuation", lambda: job_valuation(db, symbols)),
        ("factors", lambda: job_factors(db, symbols)),
    ):
        try:
            out[name] = fn()
            log.info("ingest.job.done", job=name)
        except Exception as exc:
            # One failing stage must not abort the rest of the night.
            log.error("ingest.job.failed", job=name, error=str(exc)[:300])
            out[name] = {"error": str(exc)[:300]}
    return out


JOBS: dict[str, Callable[[Session, list[str]], dict[str, Any]]] = {
    "nightly": job_nightly,
    "bars": job_bars,
    "fundamentals": job_fundamentals,
    "estimates": job_estimates,
    "valuation": job_valuation,
    "factors": job_factors,
    "instruments": lambda db, _symbols: job_instruments(db),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.ingest.jobs")
    parser.add_argument("job", choices=sorted(JOBS))
    parser.add_argument(
        "--full",
        action="store_true",
        help="Ignore daily staggering and process the whole universe.",
    )
    parser.add_argument("--symbols", help="Comma-separated symbols, overriding the universe.")
    parser.add_argument("--limit", type=int, help="Process at most N symbols (for smoke tests).")
    args = parser.parse_args(argv)

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))

    with session_scope() as db:
        explicit = bool(args.symbols)
        if explicit:
            symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        else:
            symbols = instruments.universe_symbols(db)
        if args.limit:
            symbols = symbols[: args.limit]

        if not symbols and args.job not in {"instruments", "nightly"}:
            print("No symbols. Run `python -m app.ingest.jobs instruments` first.")
            return 1

        started = time.monotonic()
        if args.job in {"fundamentals", "estimates", "valuation"}:
            # Daily staggering exists to spread the universe across a week; an
            # explicit symbol list is already the caller's chosen slice.
            fn: Any = JOBS[args.job]
            result = fn(db, symbols, full=args.full or explicit)
        else:
            result = JOBS[args.job](db, symbols)
        elapsed = time.monotonic() - started

    print(f"\n{args.job} finished in {elapsed:.1f}s")
    for key, value in result.items():
        if isinstance(value, dict):
            summary = ", ".join(
                f"{k}={len(v) if isinstance(v, list) else v}" for k, v in value.items()
            )
            print(f"  {key}: {summary}")
        else:
            print(f"  {key}: {value if not isinstance(value, list) else len(value)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
