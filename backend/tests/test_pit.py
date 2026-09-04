"""Point-in-time dating is the difference between an honest backtest and a
fantasy, so it gets tested directly."""

from __future__ import annotations

import datetime as dt

from app.ingest.pit import parse_date, resolve_known_on, statutory_known_on


def test_annual_falls_back_to_the_60_day_statutory_deadline() -> None:
    known, estimated = resolve_known_on(dt.date(2025, 3, 31), "Annual", None)
    assert known == dt.date(2025, 5, 30)
    assert estimated is True


def test_interim_falls_back_to_the_45_day_statutory_deadline() -> None:
    known, estimated = resolve_known_on(dt.date(2025, 6, 30), "Interim", None)
    assert known == dt.date(2025, 8, 14)
    assert estimated is True


def test_actual_report_date_is_preferred_over_the_estimate() -> None:
    reports = {dt.date(2025, 3, 31): dt.date(2025, 5, 12)}
    known, estimated = resolve_known_on(dt.date(2025, 3, 31), "Annual", reports)
    assert known == dt.date(2025, 5, 12)
    assert estimated is False


def test_nearby_fiscal_ends_still_match() -> None:
    """The statement and estimate feeds can disagree by a few days on where a
    period ends; that must not force a fallback."""
    reports = {dt.date(2025, 3, 30): dt.date(2025, 5, 12)}
    known, estimated = resolve_known_on(dt.date(2025, 3, 31), "Annual", reports)
    assert known == dt.date(2025, 5, 12)
    assert estimated is False


def test_a_report_date_before_the_period_end_is_rejected() -> None:
    """Guards against the broken StatementDate field, which reports dates years
    before the period it claims to describe."""
    reports = {dt.date(2026, 3, 31): dt.date(2021, 3, 31)}
    known, estimated = resolve_known_on(dt.date(2026, 3, 31), "Annual", reports)
    assert known == dt.date(2026, 5, 30)
    assert estimated is True


def test_an_implausibly_late_report_date_is_rejected() -> None:
    reports = {dt.date(2025, 3, 31): dt.date(2027, 1, 1)}
    known, estimated = resolve_known_on(dt.date(2025, 3, 31), "Annual", reports)
    assert estimated is True
    assert known == dt.date(2025, 5, 30)


def test_known_on_is_never_before_the_period_it_describes() -> None:
    for end in (dt.date(2020, 3, 31), dt.date(2024, 12, 31), dt.date(2025, 9, 30)):
        for period in ("Annual", "Interim"):
            assert statutory_known_on(end, period) > end


def test_parse_date_handles_vendor_formats() -> None:
    assert parse_date("2026-03-31") == dt.date(2026, 3, 31)
    assert parse_date("2024-05-29T09:28:00") == dt.date(2024, 5, 29)
    assert parse_date("03 Sep 2026") == dt.date(2026, 9, 3)
    assert parse_date("") is None
    assert parse_date("-") is None
    assert parse_date(None) is None
