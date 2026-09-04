"""Fundamentals derived from the statements, for any historical date.

The vendor's ~145 precomputed metrics describe *today*: one snapshot per
symbol, with no history. Snapshots accumulate from the day this platform starts
running, but a backtest needs fundamentals as they stood in 2022.

The statements do have history, and they carry ``known_on``. So the ratios a
backtest needs are recomputed from them at each rebalance date: market
capitalisation from the price on that date and the share count then reported,
trailing-twelve-month profit from the four quarters known by then, and so on.
Nothing here uses a figure the market could not have seen.

Units: statement values and share counts are in **crore** (verified -- TCS
reports 361.8, and TCS has ~362 crore shares). Prices are in rupees, so
`price x shares` gives a market capitalisation in crore, matching the vendor's
own market-cap units. This differs from the vendor's *keyMetrics* block, which
reports absolute figures in rupee million.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.factors.panel import Panel, statement_latest
from app.factors.stats import safe_divide

# Columns this module can reconstruct, mapped to how they are built below.
DERIVABLE = (
    "market_cap",
    "pe_ttm",
    "pb_fy",
    "ps_ttm",
    "roe_ttm",
    "roe_fy",
    "roa_fy",
    "debt_to_equity_fy",
    "debt_to_equity_q",
    "net_margin_ttm",
    "operating_margin_ttm",
    "gross_margin_ttm",
    "eps_ttm",
    "bvps_fy",
    "revenue_ttm",
    "net_income_ttm",
    "revenue_fy",
    "net_income_fy",
    "price_to_fcf_fy",
    "fcf_fy",
    "asset_turnover_fy",
    "current_ratio_fy",
    "interest_coverage_ttm",
    "net_debt_fy",
)


def _ttm(panel: Panel, statement: str, line_key: str) -> pd.Series:
    """Trailing twelve months from the four most recent known quarters.

    Falls back to the latest annual figure when quarterly history is short,
    which is common for smaller companies early in the sample.
    """
    df = panel.statements
    index = pd.Index(panel.symbols, name="symbol")
    if df.empty:
        return pd.Series(dtype=float, index=index)

    mask = (
        (df["statement"] == statement)
        & (df["line_key"] == line_key)
        & (df["period_type"] == "Interim")
    )
    quarterly = df[mask].dropna(subset=["value"])
    annual = statement_latest(panel, statement, line_key, "Annual")

    if quarterly.empty:
        return annual

    ordered = quarterly.sort_values(["symbol", "fiscal_end"], ascending=[True, False])
    ordered = ordered.drop_duplicates(subset=["symbol", "fiscal_end"], keep="first")
    grouped = ordered.groupby("symbol", sort=False)

    sums = grouped.head(4).groupby("symbol")["value"].sum()
    counts = grouped.head(4).groupby("symbol")["value"].count()
    # Three quarters summed is not a trailing year; fall back rather than
    # understate earnings by 25%.
    ttm = sums.where(counts >= 4)
    return ttm.reindex(index).fillna(annual)


def derive_fundamentals(panel: Panel) -> pd.DataFrame:
    """Reconstruct the fundamental columns from statements and prices."""
    index = pd.Index(panel.symbols, name="symbol")
    price = panel.latest_close.reindex(index).astype(float)

    shares = statement_latest(panel, "BAL", "TotalCommonSharesOutstanding")
    if shares.dropna().empty:
        shares = statement_latest(panel, "INC", "DilutedWeightedAverageShares")

    equity = statement_latest(panel, "BAL", "TotalEquity")
    assets = statement_latest(panel, "BAL", "TotalAssets")
    debt = statement_latest(panel, "BAL", "TotalDebt")
    current_assets = statement_latest(panel, "BAL", "TotalCurrentAssets")
    current_liabilities = statement_latest(panel, "BAL", "TotalCurrentLiabilities")
    cash = statement_latest(panel, "BAL", "Cash&Equivalents")

    revenue_ttm = _ttm(panel, "INC", "TotalRevenue")
    if revenue_ttm.dropna().empty:
        revenue_ttm = _ttm(panel, "INC", "Revenue")
    net_income_ttm = _ttm(panel, "INC", "NetIncome")
    operating_income_ttm = _ttm(panel, "INC", "OperatingIncome")
    gross_profit_ttm = _ttm(panel, "INC", "GrossProfit")
    interest_ttm = _ttm(panel, "INC", "InterestExpense-NonOperating")

    revenue_fy = statement_latest(panel, "INC", "TotalRevenue")
    net_income_fy = statement_latest(panel, "INC", "NetIncome")
    cfo = statement_latest(panel, "CAS", "CashfromOperatingActivities")
    capex = statement_latest(panel, "CAS", "CapitalExpenditures")

    # price (rupees) x shares (crore) -> market cap in crore
    market_cap = price * shares
    fcf = cfo + capex  # capex is reported negative

    out = pd.DataFrame(index=index)
    out["market_cap"] = market_cap
    out["revenue_ttm"] = revenue_ttm
    out["net_income_ttm"] = net_income_ttm
    out["revenue_fy"] = revenue_fy
    out["net_income_fy"] = net_income_fy
    out["fcf_fy"] = fcf

    out["pe_ttm"] = safe_divide(market_cap, net_income_ttm.where(net_income_ttm > 0))
    out["pb_fy"] = safe_divide(market_cap, equity.where(equity > 0))
    out["ps_ttm"] = safe_divide(market_cap, revenue_ttm.where(revenue_ttm > 0))
    out["price_to_fcf_fy"] = safe_divide(market_cap, fcf.where(fcf > 0))

    out["roe_ttm"] = safe_divide(net_income_ttm, equity.where(equity > 0)) * 100.0
    out["roe_fy"] = safe_divide(net_income_fy, equity.where(equity > 0)) * 100.0
    out["roa_fy"] = safe_divide(net_income_ttm, assets.where(assets > 0)) * 100.0

    out["debt_to_equity_fy"] = safe_divide(debt, equity.where(equity > 0))
    out["debt_to_equity_q"] = out["debt_to_equity_fy"]
    out["net_debt_fy"] = (debt - cash.fillna(0.0)) * 10.0  # crore -> million, as the vendor reports

    out["net_margin_ttm"] = safe_divide(net_income_ttm, revenue_ttm) * 100.0
    out["operating_margin_ttm"] = safe_divide(operating_income_ttm, revenue_ttm) * 100.0
    out["gross_margin_ttm"] = safe_divide(gross_profit_ttm, revenue_ttm) * 100.0

    out["eps_ttm"] = safe_divide(net_income_ttm, shares.where(shares > 0))
    out["bvps_fy"] = safe_divide(equity, shares.where(shares > 0))

    out["asset_turnover_fy"] = safe_divide(revenue_ttm, assets.where(assets > 0))
    out["current_ratio_fy"] = safe_divide(current_assets, current_liabilities)
    out["interest_coverage_ttm"] = safe_divide(
        operating_income_ttm, interest_ttm.abs().where(interest_ttm.abs() > 0)
    )

    return out.replace([np.inf, -np.inf], np.nan)


def fill_from_statements(panel: Panel) -> pd.DataFrame:
    """Merge derived values into the snapshot frame.

    The vendor's own figures win where they exist -- they are the reference and
    they cover ratios we cannot rebuild. Derived values fill the gaps, which at
    any historical date is everything.
    """
    derived = derive_fundamentals(panel)
    existing = panel.fundamentals

    if existing.empty:
        return derived

    merged = existing.copy()
    for column in derived.columns:
        if column not in merged.columns:
            merged[column] = derived[column]
        else:
            merged[column] = pd.to_numeric(merged[column], errors="coerce").fillna(derived[column])
    return merged
