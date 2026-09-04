"""Data-health reporting.

Answers "can I trust what the screener just told me?" -- how fresh the data is,
how much of the universe each table actually covers, how much of it is
point-in-time exact rather than estimated, and how much API budget is left.

All queries are cheap aggregates over small tables, because this runs in the
request path on a 512 MB instance.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.market import Universe, UniverseMember
from app.db.models.ops import IngestRun, ProviderCallDaily

settings = get_settings()


def universe_size(db: Session, slug: str = "nifty200") -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(UniverseMember)
            .join(Universe, Universe.id == UniverseMember.universe_id)
            .where(Universe.slug == slug)
        )
        or 0
    )


_SUMMARY_SQL = text(
    """
    with u as (
        select count(*) n from universe_members m
        join universes v on v.id = m.universe_id where v.slug = :slug
    ),
    b as (
        select count(*) rows, count(distinct symbol) symbols, max(date) latest from daily_bars
    ),
    f as (
        select count(*) rows, count(distinct symbol) symbols, max(snapshot_date) latest
        from fundamental_snapshots
    ),
    s as (
        select count(*) rows, count(distinct symbol) symbols,
               count(*) filter (where not known_on_estimated) exact
        from financial_statements
    ),
    e as (
        select count(*) rows, count(distinct symbol) symbols from estimates
    ),
    i as (select count(*) n from instruments)
    select u.n universe, i.n instruments,
           b.rows bar_rows, b.symbols bar_symbols, b.latest bar_latest,
           f.rows fund_rows, f.symbols fund_symbols, f.latest fund_latest,
           s.rows stmt_rows, s.symbols stmt_symbols, s.exact stmt_exact,
           e.rows est_rows, e.symbols est_symbols
    from u, b, f, s, e, i
    """
)


def _summary_row(db: Session) -> Any:
    """One round trip instead of a dozen.

    This runs in the request path on a 512 MB / ~0.1 CPU instance with the
    database in another region, so round trips dominate: the same figures split
    across separate queries took nearly four seconds.
    """
    return db.execute(_SUMMARY_SQL, {"slug": "nifty200"}).one()


def dataset_summary(db: Session, row: Any | None = None) -> list[dict[str, Any]]:
    row = row if row is not None else _summary_row(db)
    total = row.universe or 1

    def pct(symbols: int) -> float:
        return round(100 * min(symbols, total) / total, 1)

    return [
        {
            "key": "bars",
            "label": "Daily price bars",
            "symbols": row.bar_symbols,
            "rows": row.bar_rows,
            "coverage_pct": pct(row.bar_symbols),
            "latest": row.bar_latest.isoformat() if row.bar_latest else None,
            "source": "Groww",
            "note": None,
        },
        {
            "key": "fundamentals",
            "label": "Fundamental snapshots",
            "symbols": row.fund_symbols,
            "rows": row.fund_rows,
            "coverage_pct": pct(row.fund_symbols),
            "latest": row.fund_latest.isoformat() if row.fund_latest else None,
            "source": "Indian Stock API",
            "note": None,
        },
        {
            "key": "statements",
            "label": "Financial statements",
            "symbols": row.stmt_symbols,
            "rows": row.stmt_rows,
            "coverage_pct": pct(row.stmt_symbols),
            "latest": None,
            "source": "Indian Stock API",
            "note": (
                f"{round(100 * row.stmt_exact / row.stmt_rows)}% dated by actual announcement date"
                if row.stmt_rows
                else None
            ),
        },
        {
            "key": "estimates",
            "label": "Analyst estimates",
            "symbols": row.est_symbols,
            "rows": row.est_rows,
            "coverage_pct": pct(row.est_symbols),
            "latest": None,
            "source": "Indian Stock API",
            "note": None,
        },
    ]


def point_in_time_quality(db: Session, row: Any | None = None) -> dict[str, Any]:
    """How much of the fundamental history is dated by a real announcement date
    rather than the statutory filing deadline. This is the number that decides
    how far a backtest can be trusted."""
    row = row if row is not None else _summary_row(db)
    total, exact = row.stmt_rows, row.stmt_exact
    return {
        "total_rows": total,
        "exact_rows": exact,
        "estimated_rows": total - exact,
        "exact_pct": round(100 * exact / total, 1) if total else 0.0,
    }


def provider_usage(db: Session, days: int = 7) -> dict[str, Any]:
    since = dt.date.today() - dt.timedelta(days=days - 1)
    rows = db.execute(
        select(
            ProviderCallDaily.provider,
            ProviderCallDaily.call_date,
            func.sum(ProviderCallDaily.count),
            func.sum(ProviderCallDaily.error_count),
        )
        .where(ProviderCallDaily.call_date >= since)
        .group_by(ProviderCallDaily.provider, ProviderCallDaily.call_date)
        .order_by(ProviderCallDaily.call_date)
    ).all()

    history = [
        {"provider": p, "date": d.isoformat(), "calls": int(c or 0), "errors": int(e or 0)}
        for p, d, c, e in rows
    ]
    today = dt.date.today().isoformat()
    used_today = sum(
        h["calls"] for h in history if h["date"] == today and h["provider"] == "indian_api"
    )
    limit = settings.indian_api_daily_budget

    return {
        "history": history,
        "indian_api": {
            "used_today": used_today,
            "daily_budget": limit,
            "remaining": max(0, limit - used_today),
            "pct_used": round(100 * used_today / limit, 1) if limit else 0.0,
        },
    }


def recent_runs(db: Session, limit: int = 20) -> list[dict[str, Any]]:
    runs = db.scalars(select(IngestRun).order_by(IngestRun.started_at.desc()).limit(limit)).all()
    return [
        {
            "id": str(r.id),
            "job": r.job,
            "status": r.status,
            "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "duration_seconds": r.duration_seconds,
            "rows_written": r.rows_written,
            "symbols_processed": r.symbols_processed,
            "symbols_failed": r.symbols_failed,
            "api_calls": r.api_calls,
            "error": r.error,
            "details": r.details or {},
        }
        for r in runs
    ]


def overview(db: Session) -> dict[str, Any]:
    row = _summary_row(db)
    latest_bar = row.bar_latest
    staleness = (dt.date.today() - latest_bar).days if latest_bar else None

    return {
        "universe_size": row.universe,
        "instruments": row.instruments,
        "latest_bar_date": latest_bar.isoformat() if latest_bar else None,
        "bars_stale_days": staleness,
        "datasets": dataset_summary(db, row),
        "point_in_time": point_in_time_quality(db, row),
        "provider_usage": provider_usage(db),
        "recent_runs": recent_runs(db, limit=10),
    }
