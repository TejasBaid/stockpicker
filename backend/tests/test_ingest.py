"""Ingest: metric mapping, statement fan-out and point-in-time dating, all
verified against a recorded copy of the real vendor payload so a schema change
upstream breaks loudly instead of silently producing nulls."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.fundamentals import (
    CorporateAction,
    FinancialStatement,
    FundamentalSnapshot,
    Shareholding,
)
from app.db.models.market import Instrument
from app.ingest import fundamentals as fund
from app.ingest.normalize import METRIC_MAP, extract_metrics, to_float, weighted_rating

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def stock_payload() -> dict[str, Any]:
    return json.loads((FIXTURES / "stock_tatasteel.json").read_text())


# A symbol that cannot collide with real ingested rows: tests share the public
# schema with live data and rely on transaction rollback for isolation.
TEST_SYMBOL = "ZZTESTCO"


@pytest.fixture
def instrument(db: Session) -> Instrument:
    inst = Instrument(symbol=TEST_SYMBOL, name="Test Co", exchange="NSE")
    db.add(inst)
    db.commit()
    return inst


def test_every_mapped_column_exists_on_the_model() -> None:
    """Catches a rename in the model that silently stops populating a metric."""
    columns = set(FundamentalSnapshot.__table__.columns.keys())
    missing = sorted(set(METRIC_MAP.values()) - columns)
    assert missing == [], f"METRIC_MAP targets columns that do not exist: {missing}"


def test_metric_map_has_no_duplicate_targets() -> None:
    targets = list(METRIC_MAP.values())
    dupes = sorted({t for t in targets if targets.count(t) > 1})
    assert dupes == [], f"Two vendor keys write to the same column: {dupes}"


def test_extract_metrics_reads_the_real_payload(stock_payload: dict[str, Any]) -> None:
    metrics = extract_metrics(stock_payload["keyMetrics"])
    # A representative slice across all eight vendor categories.
    assert metrics["pe_ttm"] == pytest.approx(21.24)
    assert metrics["pb_fy"] == pytest.approx(2.24)
    assert metrics["roe_fy"] == pytest.approx(11.17)
    assert metrics["debt_to_equity_fy"] == pytest.approx(0.90)
    assert metrics["eps_ttm"] == pytest.approx(8.85)
    assert metrics["market_cap"] == pytest.approx(229258.43)
    assert len(metrics) > 60


def test_typo_and_spaced_vendor_keys_are_mapped(stock_payload: dict[str, Any]) -> None:
    """The vendor ships malformed keys; these are the ones that would silently
    go missing if the map were 'cleaned up'."""
    metrics = extract_metrics(stock_payload["keyMetrics"])
    assert metrics["roe_fy"] is not None  # returnOnAverageEquityMostRecentFiscalYear)
    assert metrics["roa_fy"] is not None  # ...MostRecenFiscalYear  (sic)
    assert metrics["revenue_ps_ttm"] is not None  # rRevenuePerShareTrailing12onth (sic)
    assert metrics["revenue_ttm"] is not None  # revenueTrailing12Month)
    # The spaced key is the real book value per share, not its unspaced sibling.
    assert metrics["bvps_fy"] == pytest.approx(81.92)


def test_weighted_rating_tracks_analyst_revisions(stock_payload: dict[str, Any]) -> None:
    buckets = stock_payload["stockDetailsReusableData"]["stockAnalyst"]
    latest, count = weighted_rating(buckets, "numberOfAnalystsLatest")
    older, _ = weighted_rating(buckets, "numberOfAnalysts3MonthAgo")
    assert latest is not None and older is not None
    assert count == 34  # the "Total" row must not be double counted
    assert 1.0 <= latest <= 5.0
    assert latest != older  # there is a real revision signal here


def test_to_float_handles_vendor_placeholders() -> None:
    assert to_float("1,234.50") == 1234.5
    assert to_float("-") is None
    assert to_float("") is None
    assert to_float(None) is None
    assert to_float("NA") is None
    assert to_float(True) is None  # bools must not become 1.0


def test_statements_fan_out_with_point_in_time_dates(
    db: Session, instrument: Instrument, stock_payload: dict[str, Any]
) -> None:
    written = fund._write_statements(db, TEST_SYMBOL, stock_payload, {})
    db.commit()
    assert written > 100

    rows = db.scalars(
        select(FinancialStatement).where(FinancialStatement.symbol == TEST_SYMBOL)
    ).all()
    assert {r.statement for r in rows} == {"INC", "BAL", "CAS"}
    # With no report dates supplied, everything falls back to the statutory rule.
    assert all(r.known_on_estimated for r in rows)
    for r in rows:
        assert r.known_on > r.fiscal_end


def test_real_report_dates_override_the_statutory_estimate(
    db: Session, instrument: Instrument, stock_payload: dict[str, Any]
) -> None:
    reports = {dt.date(2026, 3, 31): dt.date(2026, 5, 15)}
    fund._write_statements(db, TEST_SYMBOL, stock_payload, reports)
    db.commit()

    exact = db.scalars(
        select(FinancialStatement).where(
            FinancialStatement.symbol == TEST_SYMBOL,
            FinancialStatement.fiscal_end == dt.date(2026, 3, 31),
        )
    ).all()
    assert exact
    assert all(r.known_on == dt.date(2026, 5, 15) for r in exact)
    assert all(not r.known_on_estimated for r in exact)


def test_shareholding_and_corporate_actions_are_extracted(
    db: Session, instrument: Instrument, stock_payload: dict[str, Any]
) -> None:
    fund._write_shareholding(db, TEST_SYMBOL, stock_payload)
    fund._write_corporate_actions(db, TEST_SYMBOL, stock_payload)
    db.commit()

    holdings = db.scalars(select(Shareholding).where(Shareholding.symbol == TEST_SYMBOL)).all()
    assert {h.category for h in holdings} >= {"Promoter", "FII", "MF"}
    assert all(0 <= (h.percentage or 0) <= 100 for h in holdings)

    actions = db.scalars(select(CorporateAction).where(CorporateAction.symbol == TEST_SYMBOL)).all()
    assert actions
    assert all(a.ex_date is not None and a.value is not None for a in actions)


def test_snapshot_write_is_idempotent(
    db: Session, instrument: Instrument, stock_payload: dict[str, Any]
) -> None:
    as_of = dt.date(2026, 9, 4)
    fund._write_snapshot(db, TEST_SYMBOL, stock_payload, as_of)
    fund._write_snapshot(db, TEST_SYMBOL, stock_payload, as_of)
    db.commit()
    count = db.scalar(
        select(func.count())
        .select_from(FundamentalSnapshot)
        .where(FundamentalSnapshot.symbol == TEST_SYMBOL)
    )
    assert count == 1

    snap = db.scalars(
        select(FundamentalSnapshot).where(FundamentalSnapshot.symbol == TEST_SYMBOL)
    ).one()
    assert snap.pe_ttm == pytest.approx(21.24)
    assert snap.analyst_rating_mean is not None
    assert snap.raw  # untouched payload retained so a remap costs no API call
    assert snap.known_on <= as_of
