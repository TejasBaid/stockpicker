"""Analyst estimates, earnings surprises and price targets.

This is the highest-value endpoint after ``/stock``:

* ``ActualReportDate`` gives the real earnings announcement date, which is what
  makes point-in-time ``known_on`` real rather than a statutory guess.
* ``StandardizedUnexpectedEarnings`` and ``SurprisePercent`` drive the
  post-earnings-announcement-drift factor.
* Estimate and target revisions over time drive the revision-momentum factor.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models.fundamentals import Estimate, PriceTarget
from app.ingest.normalize import to_float
from app.ingest.pit import parse_date
from app.providers.indian_api import IndianApiClient, SymbolNotCovered

log = structlog.get_logger(__name__)

# Each (measure, period type) pair costs one request per symbol, so the default
# set is deliberately small. Interim EPS earns its call twice over: it supplies
# the quarterly earnings announcement dates that let `known_on` be real rather
# than a statutory estimate for the majority of statement rows.
DEFAULT_REQUESTS: tuple[tuple[str, str], ...] = (
    ("EPS", "Annual"),
    ("EPS", "Interim"),
    ("SAL", "Annual"),
)


def ingest_estimates(
    db: Session,
    client: IndianApiClient,
    symbols: list[str],
    *,
    requests: tuple[tuple[str, str], ...] = DEFAULT_REQUESTS,
) -> tuple[int, list[str]]:
    written = 0
    failed: list[str] = []
    for symbol in symbols:
        try:
            for measure, period_type in requests:
                written += _ingest_measure(db, client, symbol, measure, period_type)
            written += _ingest_target(db, client, symbol)
            db.commit()
        except SymbolNotCovered:
            db.rollback()
            log.info("ingest.estimates.uncovered", symbol=symbol)
        except Exception as exc:
            db.rollback()
            log.error("ingest.estimates.failed", symbol=symbol, error=str(exc)[:200])
            failed.append(symbol)
    return written, failed


def _ingest_measure(
    db: Session, client: IndianApiClient, symbol: str, measure: str, period_type: str
) -> int:
    payload = client.forecasts(symbol, measure, period_type=period_type, data_type="Actuals")
    if not isinstance(payload, dict):
        return 0

    rows: list[dict[str, Any]] = []
    for period in payload.get("periods") or []:
        if not isinstance(period, dict):
            continue
        fiscal = period.get("FiscalPeriod") or {}
        year = fiscal.get("Year")
        if year is None:
            continue

        actual_block = (period.get("Actuals") or {}).get("Actual") or []
        first = actual_block[0] if actual_block else {}
        estimate_block = (period.get("ConsensusEstimates") or {}).get("Estimate") or []
        est = estimate_block[0] if estimate_block else {}

        reported = parse_date(first.get("ReportedDate") or period.get("ActualReportDate"))
        period_end = _period_end(period.get("CalendarYear"), period.get("CalendarMonth"))

        rows.append(
            {
                "symbol": symbol,
                "measure": measure[:8],
                "period_type": str((period.get("RelativePeriod") or {}).get("Type") or period_type)[
                    :10
                ],
                "fiscal_year": int(year),
                "fiscal_month": _as_int(period.get("CalendarMonth")),
                "period_end": period_end,
                "relative_period": _as_int((period.get("RelativePeriod") or {}).get("Number")),
                "actual": to_float(first.get("Reported")),
                "mean_estimate": to_float(est.get("Mean") or first.get("SurpriseMean")),
                "high_estimate": to_float(est.get("High")),
                "low_estimate": to_float(est.get("Low")),
                "num_estimates": to_float(est.get("NumberOfEstimates")),
                "std_dev": to_float(est.get("StandardDeviation")),
                "surprise_pct": to_float(first.get("SurprisePercent")),
                "surprise_mean": to_float(first.get("SurpriseMean")),
                "sue": to_float(first.get("StandardizedUnexpectedEarnings")),
                "actual_report_date": (
                    dt.datetime.combine(reported, dt.time(), tzinfo=dt.UTC) if reported else None
                ),
                "raw": period,
            }
        )

    if not rows:
        return 0

    stmt = pg_insert(Estimate).values(rows)
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=["symbol", "measure", "period_type", "fiscal_year", "fiscal_month"],
            set_={
                c: stmt.excluded[c]
                for c in (
                    "period_end",
                    "actual",
                    "mean_estimate",
                    "high_estimate",
                    "low_estimate",
                    "num_estimates",
                    "std_dev",
                    "surprise_pct",
                    "surprise_mean",
                    "sue",
                    "actual_report_date",
                    "raw",
                )
            },
        )
    )
    return len(rows)


def _ingest_target(db: Session, client: IndianApiClient, symbol: str) -> int:
    payload = client.target_price(symbol)
    if not isinstance(payload, dict):
        return 0
    target = payload.get("priceTarget") or {}
    if not target:
        return 0

    values = {
        "symbol": symbol,
        "as_of": dt.date.today(),
        "mean": to_float(target.get("Mean")),
        "median": to_float(target.get("Median")),
        "high": to_float(target.get("High")),
        "low": to_float(target.get("Low")),
        "std_dev": to_float(target.get("StandardDeviation")),
        "num_estimates": to_float(target.get("NumberOfEstimates")),
    }
    stmt = pg_insert(PriceTarget).values(values)
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=["symbol", "as_of"],
            set_={k: stmt.excluded[k] for k in values if k not in {"symbol", "as_of"}},
        )
    )
    return 1


def _period_end(calendar_year: Any, calendar_month: Any) -> dt.date | None:
    """Last day of the calendar month the fiscal period ends in.

    ``CalendarYear`` is authoritative; ``FiscalPeriod.Year`` is the Indian
    fiscal-year label and is a year ahead for Q1-Q3.
    """
    year, month = _as_int(calendar_year), _as_int(calendar_month)
    if year is None or month is None or not 1 <= month <= 12:
        return None
    first_of_next = dt.date(year + month // 12, month % 12 + 1, 1)
    return first_of_next - dt.timedelta(days=1)


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
