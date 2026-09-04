"""Quality factors.

Where the raw statements allow it, quality is computed from them rather than
from the vendor's precomputed ratios -- accruals and cash conversion in
particular, because those are exactly the measures a company can flatter in a
headline ratio.
"""

from __future__ import annotations

import pandas as pd

from app.factors.panel import Panel, statement_latest
from app.factors.registry import register
from app.factors.stats import mask_financials, safe_divide


def _col(panel: Panel, name: str) -> pd.Series:
    if panel.fundamentals.empty or name not in panel.fundamentals.columns:
        return pd.Series(dtype=float, index=pd.Index(panel.symbols, name="symbol"))
    return pd.to_numeric(panel.fundamentals[name], errors="coerce")


@register("roe", "Return on equity", "quality", "Return on average shareholders' equity.", unit="%")
def roe(panel: Panel) -> pd.Series:
    ttm = _col(panel, "roe_ttm")
    return ttm.fillna(_col(panel, "roe_fy"))


@register(
    "roce",
    "Return on capital",
    "quality",
    "Return on invested capital -- profit against all the capital employed, debt "
    "included, so leverage cannot flatter it the way return on equity can.",
    unit="%",
)
def roce(panel: Panel) -> pd.Series:
    return _col(panel, "roi_fy").fillna(_col(panel, "roa_fy"))


@register(
    "operating_margin",
    "Operating margin",
    "quality",
    "Operating profit as a percentage of revenue.",
    unit="%",
)
def operating_margin(panel: Panel) -> pd.Series:
    return _col(panel, "operating_margin_ttm").fillna(_col(panel, "operating_margin_5y_avg"))


@register(
    "margin_stability",
    "Margin stability",
    "quality",
    "Current net margin against its own five-year average. Around 1.0 means a "
    "steady business; well below means margins are compressing.",
    unit="x",
)
def margin_stability(panel: Panel) -> pd.Series:
    return safe_divide(_col(panel, "net_margin_ttm"), _col(panel, "net_margin_5y_avg"))


@register(
    "low_leverage",
    "Low leverage",
    "quality",
    "Total debt to equity, inverted so that a conservatively financed balance sheet scores well.",
    higher_is_better=False,
    unit="x",
)
def low_leverage(panel: Panel) -> pd.Series:
    return _col(panel, "debt_to_equity_q").fillna(_col(panel, "debt_to_equity_fy"))


@register(
    "interest_coverage",
    "Interest coverage",
    "quality",
    "How many times over operating profit covers the interest bill. Not reported "
    "for lenders, where interest is a cost of goods rather than a financing burden.",
    unit="x",
)
def interest_coverage(panel: Panel) -> pd.Series:
    coverage = _col(panel, "interest_coverage_ttm").fillna(_col(panel, "interest_coverage_fy"))
    return mask_financials(coverage, panel.sectors)


@register(
    "cash_conversion",
    "Cash conversion",
    "quality",
    "Operating cash flow against reported net profit. Persistently below 1.0 means "
    "reported profits are not turning into cash.",
    unit="x",
)
def cash_conversion(panel: Panel) -> pd.Series:
    cfo = statement_latest(panel, "CAS", "CashfromOperatingActivities")
    if cfo.dropna().empty:
        cfo = statement_latest(panel, "CAS", "NetCashProvidedbyOperatingActivities")
    net_income = statement_latest(panel, "INC", "NetIncome")
    return safe_divide(cfo, net_income)


@register(
    "low_accruals",
    "Low accruals",
    "quality",
    "The gap between reported profit and operating cash flow, scaled by assets. "
    "Large positive accruals are the single most reliable warning that earnings "
    "quality is deteriorating, so this is inverted: lower accruals score higher.",
    higher_is_better=False,
    unit="x",
)
def low_accruals(panel: Panel) -> pd.Series:
    net_income = statement_latest(panel, "INC", "NetIncome")
    cfo = statement_latest(panel, "CAS", "CashfromOperatingActivities")
    if cfo.dropna().empty:
        cfo = statement_latest(panel, "CAS", "NetCashProvidedbyOperatingActivities")
    assets = statement_latest(panel, "BAL", "TotalAssets")
    return safe_divide(net_income - cfo, assets)


@register(
    "asset_turnover",
    "Asset turnover",
    "quality",
    "Revenue generated per unit of assets -- how hard the balance sheet works.",
    unit="x",
)
def asset_turnover(panel: Panel) -> pd.Series:
    return _col(panel, "asset_turnover_fy")


@register(
    "piotroski_f_score",
    "Piotroski F-Score",
    "quality",
    "The full nine-test financial-strength score: profitability, leverage and "
    "operating efficiency, each scored against the prior year. Needs year-on-year "
    "statements, which this data source provides.",
    unit="/9",
)
def piotroski_f_score(panel: Panel) -> pd.Series:
    index = pd.Index(panel.symbols, name="symbol")

    def line(statement: str, key: str, offset: int) -> pd.Series:
        return statement_latest(panel, statement, key, "Annual", offset).reindex(index)

    net_income = line("INC", "NetIncome", 0)
    net_income_prev = line("INC", "NetIncome", 1)
    assets = line("BAL", "TotalAssets", 0)
    assets_prev = line("BAL", "TotalAssets", 1)
    cfo = line("CAS", "CashfromOperatingActivities", 0)
    if cfo.dropna().empty:
        cfo = line("CAS", "NetCashProvidedbyOperatingActivities", 0)
    lt_debt = line("BAL", "TotalLongTermDebt", 0)
    lt_debt_prev = line("BAL", "TotalLongTermDebt", 1)
    current_assets = line("BAL", "TotalCurrentAssets", 0)
    current_assets_prev = line("BAL", "TotalCurrentAssets", 1)
    current_liabilities = line("BAL", "TotalCurrentLiabilities", 0)
    current_liabilities_prev = line("BAL", "TotalCurrentLiabilities", 1)
    shares = line("INC", "DilutedWeightedAverageShares", 0)
    shares_prev = line("INC", "DilutedWeightedAverageShares", 1)
    revenue = line("INC", "TotalRevenue", 0)
    revenue_prev = line("INC", "TotalRevenue", 1)
    gross_profit = line("INC", "GrossProfit", 0)
    gross_profit_prev = line("INC", "GrossProfit", 1)

    roa = safe_divide(net_income, assets)
    roa_prev = safe_divide(net_income_prev, assets_prev)
    current_ratio = safe_divide(current_assets, current_liabilities)
    current_ratio_prev = safe_divide(current_assets_prev, current_liabilities_prev)
    leverage = safe_divide(lt_debt, assets)
    leverage_prev = safe_divide(lt_debt_prev, assets_prev)
    gross_margin = safe_divide(gross_profit, revenue)
    gross_margin_prev = safe_divide(gross_profit_prev, revenue_prev)
    turnover = safe_divide(revenue, assets)
    turnover_prev = safe_divide(revenue_prev, assets_prev)

    tests = [
        net_income > 0,  # profitability
        cfo > 0,
        roa > roa_prev,
        cfo > net_income,  # accrual quality
        leverage < leverage_prev,  # leverage, liquidity, dilution
        current_ratio > current_ratio_prev,
        shares <= shares_prev,
        gross_margin > gross_margin_prev,  # operating efficiency
        turnover > turnover_prev,
    ]

    # A test with missing inputs must not silently count as a pass.
    score = pd.Series(0.0, index=index)
    coverage = pd.Series(0, index=index)
    for test, inputs in zip(
        tests,
        [
            (net_income,),
            (cfo,),
            (roa, roa_prev),
            (cfo, net_income),
            (leverage, leverage_prev),
            (current_ratio, current_ratio_prev),
            (shares, shares_prev),
            (gross_margin, gross_margin_prev),
            (turnover, turnover_prev),
        ],
        strict=True,
    ):
        known = pd.concat(inputs, axis=1).notna().all(axis=1)
        score += (test & known).astype(float)
        coverage += known.astype(int)

    # Below five usable tests the score is noise, not a low score.
    return score.where(coverage >= 5)
