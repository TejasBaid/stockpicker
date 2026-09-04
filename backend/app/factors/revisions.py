"""Analyst revision and earnings-surprise factors.

The strongest short-horizon signals in this dataset. Both rest on fields most
retail screeners never see: the consensus rating at several past vintages, and
standardised unexpected earnings with the actual announcement date.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from app.factors.panel import Panel
from app.factors.registry import register
from app.factors.stats import safe_divide

# Post-earnings drift decays over roughly a quarter.
PEAD_HALFLIFE_DAYS = 45.0
PEAD_MAX_AGE_DAYS = 120


def _col(panel: Panel, name: str) -> pd.Series:
    if panel.fundamentals.empty or name not in panel.fundamentals.columns:
        return pd.Series(dtype=float, index=pd.Index(panel.symbols, name="symbol"))
    return pd.to_numeric(panel.fundamentals[name], errors="coerce")


@register(
    "rating_revision",
    "Analyst rating revision",
    "revisions",
    "Improvement in the consensus rating over the past three months. The vendor "
    "reports analyst counts per rating bucket at several past vintages, so this is "
    "a genuine change in view rather than a snapshot of the level.",
    sector_neutral=False,
    unit="pts",
)
def rating_revision(panel: Panel) -> pd.Series:
    # Ratings run 1 (strong buy) to 5 (strong sell), so a fall is an upgrade.
    return _col(panel, "analyst_rating_mean_3m_ago") - _col(panel, "analyst_rating_mean")


@register(
    "rating_level",
    "Analyst rating",
    "revisions",
    "Current consensus rating, inverted so that a stronger buy scores higher.",
    higher_is_better=False,
    sector_neutral=False,
    unit="1-5",
)
def rating_level(panel: Panel) -> pd.Series:
    return _col(panel, "analyst_rating_mean")


@register(
    "target_upside",
    "Analyst target upside",
    "revisions",
    "Consensus twelve-month price target against the current price.",
    sector_neutral=False,
    unit="%",
)
def target_upside(panel: Panel) -> pd.Series:
    index = pd.Index(panel.symbols, name="symbol")
    if panel.targets.empty:
        return pd.Series(dtype=float, index=index)
    targets = panel.targets.set_index("symbol")["mean"].reindex(index).astype(float)
    price = panel.latest_close.reindex(index).astype(float)
    return (safe_divide(targets, price) - 1.0) * 100.0


@register(
    "earnings_surprise",
    "Earnings surprise (SUE)",
    "revisions",
    "Standardised unexpected earnings from the most recent result, decayed by time "
    "since the announcement. Post-earnings drift is real but fades over roughly a "
    "quarter, so a beat reported last week counts for far more than one reported "
    "three months ago.",
    sector_neutral=False,
    unit="sd",
)
def earnings_surprise(panel: Panel) -> pd.Series:
    index = pd.Index(panel.symbols, name="symbol")
    est = panel.estimates
    if est.empty or "sue" not in est.columns:
        return pd.Series(dtype=float, index=index)

    rows = est.dropna(subset=["sue", "actual_report_date"]).copy()
    if rows.empty:
        return pd.Series(dtype=float, index=index)

    rows["report_date"] = pd.to_datetime(rows["actual_report_date"], utc=True).dt.date
    rows = rows.sort_values("report_date").groupby("symbol").last()

    as_of = panel.as_of
    age = rows["report_date"].apply(lambda d: (as_of - d).days).astype(float)
    decay = np.power(0.5, age / PEAD_HALFLIFE_DAYS)
    decayed = rows["sue"].astype(float) * decay
    decayed = decayed.where(age <= PEAD_MAX_AGE_DAYS)
    return decayed.reindex(index)


@register(
    "surprise_percent",
    "Earnings beat",
    "revisions",
    "Percentage by which the last reported result beat or missed consensus.",
    sector_neutral=False,
    unit="%",
)
def surprise_percent(panel: Panel) -> pd.Series:
    index = pd.Index(panel.symbols, name="symbol")
    est = panel.estimates
    if est.empty or "surprise_pct" not in est.columns:
        return pd.Series(dtype=float, index=index)
    rows = est.dropna(subset=["surprise_pct", "actual_report_date"]).copy()
    if rows.empty:
        return pd.Series(dtype=float, index=index)
    rows["report_date"] = pd.to_datetime(rows["actual_report_date"], utc=True).dt.date
    latest = rows.sort_values("report_date").groupby("symbol").last()
    cutoff = panel.as_of - dt.timedelta(days=PEAD_MAX_AGE_DAYS)
    latest = latest[latest["report_date"] >= cutoff]
    return latest["surprise_pct"].astype(float).reindex(index)
