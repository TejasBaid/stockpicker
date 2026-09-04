"""Fundamentals ingest from the Indian Stock API's ``/stock`` endpoint.

A single call returns, per symbol: ~145 key metrics, 8 annual and 11 interim
periods of income statement / balance sheet / cash flow, quarterly
shareholding, a peer list, and analyst ratings with three months of history.
This module fans that one payload out across five tables.

Snapshots are append-only (keyed by ``snapshot_date``), so repeated runs build
a real time series that the vendor itself does not expose.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models.fundamentals import (
    CorporateAction,
    Estimate,
    FinancialStatement,
    FundamentalSnapshot,
    Shareholding,
)
from app.db.models.market import Instrument
from app.ingest.normalize import extract_metrics, to_float, weighted_rating
from app.ingest.pit import parse_date, resolve_known_on
from app.providers.indian_api import IndianApiClient, SymbolNotCovered

log = structlog.get_logger(__name__)

STATEMENT_KEYS = ("INC", "BAL", "CAS")


def report_dates_for(db: Session, symbol: str) -> dict[dt.date, dt.date]:
    """Actual earnings announcement dates, from previously ingested estimates.

    This is what lets ``known_on`` be real rather than a statutory guess.
    """
    rows = db.execute(
        select(Estimate.period_end, Estimate.actual_report_date).where(
            Estimate.symbol == symbol,
            Estimate.actual_report_date.is_not(None),
            Estimate.period_end.is_not(None),
        )
    ).all()
    out: dict[dt.date, dt.date] = {}
    for period_end, reported in rows:
        if period_end is None or reported is None:
            continue
        out[period_end] = reported.date() if isinstance(reported, dt.datetime) else reported
    return out


def ingest_stock(
    db: Session, client: IndianApiClient, symbol: str, *, as_of: dt.date | None = None
) -> dict[str, int]:
    """Ingest one symbol. Returns per-table row counts."""
    as_of = as_of or dt.date.today()
    inst = db.get(Instrument, symbol)
    payload = client.stock(symbol, lookup_name=inst.vendor_lookup_name if inst else None)
    reports = report_dates_for(db, symbol)

    counts = {
        "snapshot": _write_snapshot(db, symbol, payload, as_of),
        "statements": _write_statements(db, symbol, payload, reports),
        "shareholding": _write_shareholding(db, symbol, payload),
        "corporate_actions": _write_corporate_actions(db, symbol, payload),
    }
    _update_instrument_identity(db, symbol, payload)
    db.commit()
    return counts


def _update_instrument_identity(db: Session, symbol: str, payload: dict[str, Any]) -> None:
    profile = payload.get("companyProfile") or {}
    inst = db.get(Instrument, symbol)
    if inst is None:
        return
    if not inst.industry and payload.get("industry"):
        inst.industry = str(payload["industry"])[:160]
    if not inst.isin and profile.get("isInId"):
        inst.isin = str(profile["isInId"])[:12]
    if not inst.bse_code and profile.get("exchangeCodeBse"):
        inst.bse_code = str(profile["exchangeCodeBse"])[:20]


def _write_snapshot(db: Session, symbol: str, payload: dict[str, Any], as_of: dt.date) -> int:
    metrics = extract_metrics(payload.get("keyMetrics"))

    analysts = (payload.get("stockDetailsReusableData") or {}).get("stockAnalyst")
    latest, count = weighted_rating(analysts, "numberOfAnalystsLatest")
    month_ago, _ = weighted_rating(analysts, "numberOfAnalysts1MonthAgo")
    three_ago, _ = weighted_rating(analysts, "numberOfAnalysts3MonthAgo")

    risk = payload.get("riskMeter") or {}

    # The snapshot describes the latest reported period, so date it by the most
    # recent statement rather than by when we happened to fetch it.
    latest_end = _latest_fiscal_end(payload)
    known_on, estimated = (
        resolve_known_on(latest_end, "Interim", report_dates_for(db, symbol))
        if latest_end
        else (as_of, True)
    )
    known_on = min(known_on, as_of)

    values: dict[str, Any] = {
        "symbol": symbol,
        "snapshot_date": as_of,
        "known_on": known_on,
        "known_on_estimated": estimated,
        "analyst_rating_mean": latest,
        "analyst_count": count or None,
        "analyst_rating_mean_1m_ago": month_ago,
        "analyst_rating_mean_3m_ago": three_ago,
        "risk_std_dev": to_float(risk.get("stdDev")),
        "risk_category": (str(risk["categoryName"])[:60] if risk.get("categoryName") else None),
        "raw": payload.get("keyMetrics") or {},
        **metrics,
    }

    stmt = pg_insert(FundamentalSnapshot).values(values)
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=["symbol", "snapshot_date"],
            set_={k: stmt.excluded[k] for k in values if k not in {"symbol", "snapshot_date"}},
        )
    )
    return 1


def _latest_fiscal_end(payload: dict[str, Any]) -> dt.date | None:
    ends = [
        parse_date(f.get("EndDate"))
        for f in (payload.get("financials") or [])
        if isinstance(f, dict)
    ]
    real = [e for e in ends if e is not None]
    return max(real) if real else None


def _write_statements(
    db: Session,
    symbol: str,
    payload: dict[str, Any],
    reports: dict[dt.date, dt.date],
) -> int:
    rows: list[dict[str, Any]] = []
    for period in payload.get("financials") or []:
        if not isinstance(period, dict):
            continue
        fiscal_end = parse_date(period.get("EndDate"))
        if fiscal_end is None:
            continue
        period_type = str(period.get("Type") or "Annual")
        known_on, estimated = resolve_known_on(fiscal_end, period_type, reports)

        statement_map = period.get("stockFinancialMap") or {}
        for statement in STATEMENT_KEYS:
            for line in statement_map.get(statement) or []:
                if not isinstance(line, dict):
                    continue
                key = str(line.get("key") or "").strip()
                if not key:
                    continue
                rows.append(
                    {
                        "symbol": symbol,
                        "fiscal_end": fiscal_end,
                        "fiscal_year": str(period.get("FiscalYear") or "")[:8] or None,
                        "period_type": period_type[:10],
                        "statement": statement,
                        "line_key": key[:120],
                        "display_name": (str(line.get("displayName") or "").strip() or None),
                        "value": to_float(line.get("value")),
                        "known_on": known_on,
                        "known_on_estimated": estimated,
                    }
                )

    for i in range(0, len(rows), 1000):
        chunk = rows[i : i + 1000]
        stmt = pg_insert(FinancialStatement).values(chunk)
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=[
                    "symbol",
                    "fiscal_end",
                    "period_type",
                    "statement",
                    "line_key",
                ],
                set_={
                    "value": stmt.excluded.value,
                    "known_on": stmt.excluded.known_on,
                    "known_on_estimated": stmt.excluded.known_on_estimated,
                    "display_name": stmt.excluded.display_name,
                },
            )
        )
    return len(rows)


def _write_shareholding(db: Session, symbol: str, payload: dict[str, Any]) -> int:
    rows: list[dict[str, Any]] = []
    for group in payload.get("shareholding") or []:
        if not isinstance(group, dict):
            continue
        category = str(group.get("displayName") or group.get("categoryName") or "").strip()[:40]
        if not category:
            continue
        for entry in group.get("categories") or []:
            holding_date = parse_date(entry.get("holdingDate"))
            pct = to_float(entry.get("percentage"))
            if holding_date is None or pct is None:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "holding_date": holding_date,
                    "category": category,
                    "percentage": pct,
                }
            )
    if rows:
        stmt = pg_insert(Shareholding).values(rows)
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["symbol", "holding_date", "category"],
                set_={"percentage": stmt.excluded.percentage},
            )
        )
    return len(rows)


def _write_corporate_actions(db: Session, symbol: str, payload: dict[str, Any]) -> int:
    data = payload.get("stockCorporateActionData") or {}
    rows: list[dict[str, Any]] = []
    for action_type, entries in data.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            ex_date = parse_date(entry.get("xdDate")) or parse_date(entry.get("sortDate"))
            rows.append(
                {
                    "symbol": symbol,
                    "action_type": str(action_type)[:30],
                    "ex_date": ex_date,
                    "record_date": parse_date(entry.get("recordDate")),
                    "announced_date": parse_date(entry.get("dateOfAnnouncement")),
                    "value": to_float(entry.get("value")),
                    "percentage": to_float(entry.get("percentage")),
                    "interim_or_final": (
                        str(entry["interimOrFinal"])[:20] if entry.get("interimOrFinal") else None
                    ),
                    "remarks": (str(entry["remarks"])[:500] if entry.get("remarks") else None),
                }
            )

    # The unique key includes `value`, which may be null; Postgres treats nulls
    # as distinct, so drop rows that cannot be de-duplicated reliably.
    rows = [r for r in rows if r["ex_date"] is not None and r["value"] is not None]
    if rows:
        stmt = pg_insert(CorporateAction).values(rows)
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["symbol", "action_type", "ex_date", "value"],
                set_={
                    "record_date": stmt.excluded.record_date,
                    "announced_date": stmt.excluded.announced_date,
                    "percentage": stmt.excluded.percentage,
                    "remarks": stmt.excluded.remarks,
                },
            )
        )
    return len(rows)


def ingest_fundamentals(
    db: Session,
    client: IndianApiClient,
    symbols: list[str],
    *,
    as_of: dt.date | None = None,
) -> tuple[int, list[str], list[str]]:
    """Returns (rows written, failed symbols, symbols the vendor does not cover)."""
    written = 0
    failed: list[str] = []
    uncovered: list[str] = []

    for symbol in symbols:
        try:
            counts = ingest_stock(db, client, symbol, as_of=as_of)
            written += sum(counts.values())
            log.info("ingest.fundamentals.ok", symbol=symbol, **counts)
        except SymbolNotCovered as exc:
            log.warning("ingest.fundamentals.uncovered", symbol=symbol, error=str(exc)[:160])
            uncovered.append(symbol)
            inst = db.get(Instrument, symbol)
            if inst is not None:
                inst.fundamentals_available = False
                db.commit()
        except Exception as exc:
            db.rollback()
            log.error("ingest.fundamentals.failed", symbol=symbol, error=str(exc)[:200])
            failed.append(symbol)

    return written, failed, uncovered
