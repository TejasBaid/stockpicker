"""Ownership and flow factors.

Quarterly shareholding filings show whether institutions and promoters are
adding or trimming -- a slower signal than price, but one that rarely reverses
without reason.
"""

from __future__ import annotations

import pandas as pd

from app.factors.panel import Panel
from app.factors.registry import register


def _delta(panel: Panel, category: str, quarters: int = 2) -> pd.Series:
    index = pd.Index(panel.symbols, name="symbol")
    rows = panel.shareholding
    if rows.empty:
        return pd.Series(dtype=float, index=index)

    subset = rows[rows["category"] == category]
    if subset.empty:
        return pd.Series(dtype=float, index=index)

    # Ranked within each symbol: filing dates are not aligned across companies,
    # so a shared column position is not "the latest quarter" for everyone.
    ordered = subset.dropna(subset=["percentage"]).sort_values(
        ["symbol", "holding_date"], ascending=[True, False]
    )
    ordered = ordered.drop_duplicates(subset=["symbol", "holding_date"], keep="first")
    grouped = ordered.groupby("symbol", sort=False)

    latest = grouped.nth(0).set_index("symbol")["percentage"].astype(float)
    earlier = grouped.nth(quarters).set_index("symbol")["percentage"].astype(float)
    if earlier.empty:
        # Fall back to the oldest available quarter when history is short.
        earlier = grouped.tail(1).set_index("symbol")["percentage"].astype(float)
    return (latest - earlier).reindex(index)


@register(
    "fii_accumulation",
    "FII accumulation",
    "ownership",
    "Change in foreign institutional holding over the last two reported quarters.",
    sector_neutral=False,
    unit="pp",
)
def fii_accumulation(panel: Panel) -> pd.Series:
    return _delta(panel, "FII")


@register(
    "mf_accumulation",
    "Mutual fund accumulation",
    "ownership",
    "Change in domestic mutual fund and insurance holding over the last two reported quarters.",
    sector_neutral=False,
    unit="pp",
)
def mf_accumulation(panel: Panel) -> pd.Series:
    return _delta(panel, "MF")


@register(
    "promoter_holding_change",
    "Promoter holding change",
    "ownership",
    "Change in promoter holding. Promoters selling into strength is worth knowing; "
    "promoters buying is one of the few genuinely informed signals available.",
    sector_neutral=False,
    unit="pp",
)
def promoter_holding_change(panel: Panel) -> pd.Series:
    return _delta(panel, "Promoter")


@register(
    "promoter_skin_in_the_game",
    "Promoter holding",
    "ownership",
    "Absolute promoter stake. High promoter ownership aligns management with "
    "shareholders, though it can also mean a thin free float.",
    sector_neutral=False,
    unit="%",
)
def promoter_skin_in_the_game(panel: Panel) -> pd.Series:
    index = pd.Index(panel.symbols, name="symbol")
    rows = panel.shareholding
    if rows.empty:
        return pd.Series(dtype=float, index=index)
    subset = rows[rows["category"] == "Promoter"]
    if subset.empty:
        return pd.Series(dtype=float, index=index)
    latest = subset.sort_values("holding_date").groupby("symbol").last()
    return latest["percentage"].astype(float).reindex(index)
