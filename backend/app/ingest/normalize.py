"""Mapping from the vendor's metric keys to our columns.

The Indian Stock API's ``keyMetrics`` payload has genuinely malformed keys --
stray trailing parentheses (``returnOnAverageEquityMostRecentFiscalYear)``),
misspellings (``returnOnAverageAssetsMostRecenFiscalYear``,
``rRevenuePerShareTrailing12onth``) and embedded spaces
(``bookValuePerShare MostRecentFiscalYear``). They are mapped literally here
rather than "cleaned", because cleaning them collides: ``persharedata``
contains *both* ``bookValuePerShare MostRecentFiscalYear`` (81.92 for Tata
Steel, the real book value per share) and ``bookValuePerShareMostRecentFiscalYear``
(65.13, a different series). Normalising away the space would silently merge
two different numbers.

Anything not mapped here is still preserved in ``fundamental_snapshots.raw``,
so adding a column later never costs an API call.
"""

from __future__ import annotations

from typing import Any

# vendor key -> our column name
METRIC_MAP: dict[str, str] = {
    # --- valuation ---
    "pPerEBasicExcludingExtraordinaryItemsTTM": "pe_ttm",
    "pPerEExcludingExtraordinaryItemsMostRecentFiscalYear": "pe_fy",
    "pPerENormalizedMostRecentFiscalYear": "pe_normalized_fy",
    "priceToBookMostRecentFiscalYear": "pb_fy",
    "priceToBookMostRecentQuarter": "pb_q",
    "priceToTangibleBookMostFiscalYear": "price_to_tangible_book_fy",
    "priceToSalesTrailing12Month": "ps_ttm",
    "priceToSalesMostRecentFiscalYear": "ps_fy",
    "pegRatio": "peg",
    "dividendYieldIndicatedAnnualDividendDividedByClosingprice": "dividend_yield",
    "dividendYield5YearAverage": "dividend_yield_5y_avg",
    "priceToFreeCashFlowPerShareMostRecentFiscalYear": "price_to_fcf_fy",
    "priceToCashFlowPerShareTrailing12Month": "price_to_cashflow_ttm",
    "currentEVPerFreeCashFlowLFY": "ev_to_fcf_fy",
    "netDebtLFY": "net_debt_fy",
    # --- management effectiveness ---
    "returnOnAverageEquityMostRecentFiscalYear)": "roe_fy",
    "returnOnAverageEquityTrailing12Month": "roe_ttm",
    "returnOnAverageEquity5YearAverage": "roe_5y_avg",
    "returnOnAverageAssetsMostRecenFiscalYear": "roa_fy",
    "returnOnAverageAssets5YearAverage": "roa_5y_avg",
    "returnOnInvestmentMostRecentFiscalYear": "roi_fy",
    "returnOnInvestment5YearAverage": "roi_5y_avg",
    "assetTurnoverMostRecentFiscalYear": "asset_turnover_fy",
    "inventoryTurnoverMostRecentFiscalYear": "inventory_turnover_fy",
    "receivablesTurnoverMostRecentFiscalYear": "receivables_turnover_fy",
    # --- margins ---
    "grossMarginTrailing12Month": "gross_margin_ttm",
    "grossMargin5YearAverage": "gross_margin_5y_avg",
    "operatingMarginTrailing12Month": "operating_margin_ttm",
    "operatingMargin5YearAverage": "operating_margin_5y_avg",
    "netProfitMarginPercentTrailing12Month": "net_margin_ttm",
    "netProfitMargin5YearAverage": "net_margin_5y_avg",
    "pretaxMarginTrailing12Month": "pretax_margin_ttm",
    "freeOperatingCashFlowPerRevenue5YearAverage": "fcf_per_revenue_5y_avg",
    # --- financial strength ---
    "totalDebtPerTotalEquityMostRecentFiscalYear": "debt_to_equity_fy",
    "totalDebtPerTotalEquityMostRecentQuarter": "debt_to_equity_q",
    "ltDebtPerEquityMostRecentFiscalYear)": "lt_debt_to_equity_fy",
    "currentRatioMostRecentFiscalYear": "current_ratio_fy",
    "quickRatioMostRecentFiscalYear": "quick_ratio_fy",
    "netInterestCoverageTrailing12Month": "interest_coverage_ttm",
    "netInterestCoverageMostRecentFiscalYear": "interest_coverage_fy",
    "payoutRatioTrailing12Month": "payout_ratio_ttm",
    "freeCashFlowMostRecentFiscalYear": "fcf_fy",
    # --- growth ---
    "ePSChangePercentTTMOverTTM": "eps_growth_ttm",
    "growthRatePercentEPS3year": "eps_cagr_3y",
    "ePSGrowthRate5Year": "eps_cagr_5y",
    "ePSChangePercentMostRecentQuarter1YearAgo)": "eps_growth_q_yoy",
    "revenueChangePercentTTMPOverTTM": "revenue_growth_ttm",
    "growthRatePercentRevenue3Year": "revenue_cagr_3y",
    "revenueGrowthRate5Year": "revenue_cagr_5y",
    "revenueChangePercentMostRecentQuarter1YearAgo": "revenue_growth_q_yoy",
    "bookValuePerShareGrowthRate5Year": "bvps_growth_5y",
    "earningsBeforeInterestTaxesDepreciationAmortization5YearCAGR": "ebitda_cagr_5y",
    "freeOperatingCashFlow5YearCAGR": "fcf_cagr_5y",
    "netProfitMarginGrowthRate5Year": "net_margin_growth_5y",
    # --- per share ---
    "ePSBasicExcludingExtraordinaryItemsItrailing12Month": "eps_ttm",
    "ePSBasicExcludingExtraordinaryItemsMostRecentFiscalYear": "eps_fy",
    "ePSNormalizedMostRecentFiscalYear": "eps_normalized_fy",
    # NOTE: the space is intentional -- this is the real book value per share.
    "bookValuePerShare MostRecentFiscalYear": "bvps_fy",
    "dividendsPerShareTrailing12Month": "dps_ttm",
    "cashFlowPerShareTrailing12Month": "cfps_ttm",
    "rRevenuePerShareTrailing12onth": "revenue_ps_ttm",
    "cashPerShareMostRecentFiscalYear": "cash_ps_fy",
    # --- income statement ---
    "revenueTrailing12Month)": "revenue_ttm",
    "revenueMostRecentFiscalYear": "revenue_fy",
    "netIncomeAvailableToCommonTrailing12Months": "net_income_ttm",
    "netIncomeAvailableToCommonMostRecentFiscalYear": "net_income_fy",
    "eBITDTrailing12Month": "ebitda_ttm",
    "eBITDMostRecentFiscalYear": "ebitda_fy",
    "earningsBeforeTaxesTrailing12Month": "ebt_ttm",
    # --- price & volume ---
    "marketCap": "market_cap",
    "beta": "beta",
    "52WeekHigh": "week52_high",
    "52WeekLow": "week52_low",
    "avgTradingVolumeLast10Days": "avg_volume_10d",
    "avgTradingVolumeLast3months": "avg_volume_3m",
    "relativePricePercentChange13Week": "rel_perf_13w",
    "relativePricePercentChange26Week": "rel_perf_26w",
    "relativePricePercentChange52Week": "rel_perf_52w",
    "relativePricePercentChangeYearToDate": "rel_perf_ytd",
}

# Ratings are returned as counts per bucket with 1w/1m/2m/3m history, which is
# what makes an analyst-revision factor possible.
RATING_VALUES = {"Strong Buy": 1.0, "Buy": 2.0, "Hold": 3.0, "Sell": 4.0, "Strong Sell": 5.0}


def to_float(value: Any) -> float | None:
    """Vendor numbers arrive as strings, sometimes as '-' or '' for missing."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return None if isinstance(value, bool) else float(value)
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "--", "NA", "N/A", "null", "None"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def extract_metrics(key_metrics: dict[str, Any] | None) -> dict[str, float]:
    """Flatten ``keyMetrics``'s eight categories into our column names."""
    out: dict[str, float] = {}
    if not isinstance(key_metrics, dict):
        return out
    for entries in key_metrics.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            column = METRIC_MAP.get(str(entry.get("key", "")))
            if column is None:
                continue
            value = to_float(entry.get("value"))
            if value is not None:
                out[column] = value
    return out


def weighted_rating(buckets: list[dict[str, Any]] | None, field: str) -> tuple[float | None, float]:
    """Consensus rating (1 = strong buy .. 5 = strong sell) and analyst count
    for one point in time, from the per-bucket analyst counts.

    ``field`` selects the vintage: ``numberOfAnalystsLatest``,
    ``numberOfAnalysts1MonthAgo``, ``numberOfAnalysts3MonthAgo``, ...
    """
    if not isinstance(buckets, list):
        return None, 0.0
    total = 0.0
    weighted = 0.0
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        name = str(bucket.get("ratingName", ""))
        if name not in RATING_VALUES:  # skips the "Total" row
            continue
        count = to_float(bucket.get(field)) or 0.0
        weighted += RATING_VALUES[name] * count
        total += count
    if total == 0:
        return None, 0.0
    return weighted / total, total
