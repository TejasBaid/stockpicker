"""Daily OHLCV ingest from Groww.

Backfills incrementally: each symbol is fetched only from the day after its
latest stored bar, so a nightly run costs one short request per symbol while
the first run pulls the full history.
"""

from __future__ import annotations

import datetime as dt
from itertools import pairwise

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models.market import DailyBar
from app.providers.groww import GrowwClient

log = structlog.get_logger(__name__)

DEFAULT_HISTORY_YEARS = 6


def latest_bar_dates(db: Session, symbols: list[str]) -> dict[str, dt.date]:
    rows = db.execute(
        select(DailyBar.symbol, func.max(DailyBar.date))
        .where(DailyBar.symbol.in_(symbols))
        .group_by(DailyBar.symbol)
    ).all()
    return {symbol: latest for symbol, latest in rows if latest is not None}


def ingest_bars(
    db: Session,
    symbols: list[str],
    *,
    client: GrowwClient | None = None,
    history_years: int = DEFAULT_HISTORY_YEARS,
    end: dt.date | None = None,
) -> tuple[int, int, list[str]]:
    """Returns (rows written, symbols processed, symbols that failed)."""
    client = client or GrowwClient()
    end = end or dt.date.today()
    earliest = end - dt.timedelta(days=int(history_years * 365.25))
    latest = latest_bar_dates(db, symbols)

    rows_written = 0
    processed = 0
    failed: list[str] = []

    for symbol in symbols:
        have = latest.get(symbol)
        start = (have + dt.timedelta(days=1)) if have else earliest
        if start > end:
            processed += 1
            continue
        try:
            candles = client.daily_candles(symbol, start, end)
        except Exception as exc:
            log.warning("ingest.bars.failed", symbol=symbol, error=str(exc)[:200])
            failed.append(symbol)
            continue

        if candles:
            values = [
                {
                    "symbol": symbol,
                    "date": c.date,
                    # The current vendor endpoint returns a null open for daily
                    # equity candles; fall back to close so the column stays
                    # non-null and charts degrade to a flat body rather than
                    # breaking.
                    "open": c.open if c.open is not None else c.close,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                }
                for c in candles
                if c.close > 0
            ]
            for i in range(0, len(values), 1000):
                chunk = values[i : i + 1000]
                stmt = pg_insert(DailyBar).values(chunk)
                db.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["symbol", "date"],
                        set_={
                            "open": stmt.excluded.open,
                            "high": stmt.excluded.high,
                            "low": stmt.excluded.low,
                            "close": stmt.excluded.close,
                            "volume": stmt.excluded.volume,
                        },
                    )
                )
                rows_written += len(chunk)
            db.commit()
        processed += 1

    log.info("ingest.bars.done", rows=rows_written, processed=processed, failed=len(failed))
    return rows_written, processed, failed


def detect_unadjusted_splits(db: Session, symbols: list[str], threshold: float = 0.35) -> list[str]:
    """Flag series with an overnight move large enough to be an unadjusted
    split or bonus.

    Groww does not document whether its history is adjusted for corporate
    actions, and an unadjusted split would wreck every momentum and moving
    average factor. Rather than assume, we look for the signature: a single-day
    close-to-close change of 35%+ with no matching move in the index.
    """
    suspicious: list[str] = []
    for symbol in symbols:
        closes = db.execute(
            select(DailyBar.date, DailyBar.close)
            .where(DailyBar.symbol == symbol)
            .order_by(DailyBar.date)
        ).all()
        for (_, prev), (day, curr) in pairwise(closes):
            if prev and curr and abs(curr / prev - 1.0) >= threshold:
                log.warning(
                    "ingest.bars.possible_unadjusted_action",
                    symbol=symbol,
                    date=str(day),
                    ratio=round(curr / prev, 3),
                )
                suspicious.append(symbol)
                break
    return suspicious
