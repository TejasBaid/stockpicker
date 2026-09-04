"""Valuation-multiple history from ``/historical_data``.

Supports the "cheap relative to its own history" family of factors, which plain
cross-sectional value screens miss: a bank on 12x looks expensive next to a
steelmaker on 8x, but cheap next to its own five-year median of 18x.

The price series here is weekly, so it is *not* used for bars -- Groww remains
the source of truth for daily OHLCV.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models.fundamentals import ValuationHistory
from app.ingest.normalize import to_float
from app.ingest.pit import parse_date
from app.providers.indian_api import IndianApiClient, SymbolNotCovered

log = structlog.get_logger(__name__)

# Each filter costs one call per symbol. Only the P/E series is consumed today
# (by the "cheap vs its own history" factor), so the others are opt-in rather
# than quietly quadrupling the nightly bill.
DEFAULT_FILTERS = ("pe",)


def ingest_valuation_history(
    db: Session,
    client: IndianApiClient,
    symbols: list[str],
    *,
    period: str = "5yr",
    filters: tuple[str, ...] = DEFAULT_FILTERS,
) -> tuple[int, list[str]]:
    written = 0
    failed: list[str] = []
    for symbol in symbols:
        try:
            for metric in filters:
                payload = client.historical_data(symbol, period=period, filter_=metric)
                written += _write_series(db, symbol, metric, payload)
            db.commit()
        except SymbolNotCovered:
            db.rollback()
        except Exception as exc:
            db.rollback()
            log.error("ingest.valuation.failed", symbol=symbol, error=str(exc)[:200])
            failed.append(symbol)
    return written, failed


def _write_series(db: Session, symbol: str, metric: str, payload: Any) -> int:
    points = _extract_points(payload)
    rows = []
    for raw_date, raw_value in points:
        day = parse_date(raw_date)
        value = to_float(raw_value)
        if day is None or value is None:
            continue
        rows.append({"symbol": symbol, "date": day, "metric": metric[:20], "value": value})
    if not rows:
        return 0

    for i in range(0, len(rows), 1000):
        chunk = rows[i : i + 1000]
        stmt = pg_insert(ValuationHistory).values(chunk)
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["symbol", "date", "metric"],
                set_={"value": stmt.excluded.value},
            )
        )
    return len(rows)


def _extract_points(payload: Any) -> list[tuple[Any, Any]]:
    """The endpoint returns two different shapes: a bare list of [date, value]
    pairs for valuation filters, and a {"datasets": [{"metric", "values"}]}
    envelope for the price filter."""
    if isinstance(payload, dict):
        datasets = payload.get("datasets")
        if isinstance(datasets, list):
            for ds in datasets:
                if isinstance(ds, dict) and isinstance(ds.get("values"), list):
                    return [
                        tuple(v[:2]) for v in ds["values"] if isinstance(v, list) and len(v) >= 2
                    ]
            return []
    if isinstance(payload, list):
        return [(v[0], v[1]) for v in payload if isinstance(v, list) and len(v) >= 2]
    return []
