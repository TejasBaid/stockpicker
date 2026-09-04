"""Value factors.

Multiples are inverted into yields before scoring. A P/E of 5 and a P/E of 50
are not "45 apart" in any meaningful sense, but their earnings yields (20% and
2%) are directly comparable and average sensibly. Negative multiples become
missing rather than extreme, since a negative P/E is not cheap.
"""

from __future__ import annotations

import pandas as pd

from app.factors.panel import Panel
from app.factors.registry import register
from app.factors.stats import inverse, mask_financials, safe_divide

# The vendor reports market capitalisation in rupee crore but every absolute
# statement and balance-sheet figure in rupee million -- verified against known
# values (Reliance: market_cap 1,769,176 = Rs 17.7 lakh crore; revenue_ttm
# 11,388,650 = Rs 11.4 lakh crore). Any factor mixing the two must convert, or
# it is wrong by a factor of ten.
CRORE_TO_MILLION = 10.0


def _yield_pct(multiple: pd.Series) -> pd.Series:
    """Turn a valuation multiple into a percentage yield.

    Reported as a percentage rather than a raw reciprocal because that is how
    the number is actually read: a P/E of 10 is a 10% earnings yield, not 0.1.
    """
    return inverse(multiple) * 100.0


def _col(panel: Panel, name: str) -> pd.Series:
    if panel.fundamentals.empty or name not in panel.fundamentals.columns:
        return pd.Series(dtype=float, index=pd.Index(panel.symbols, name="symbol"))
    return pd.to_numeric(panel.fundamentals[name], errors="coerce")


@register(
    "earnings_yield",
    "Earnings yield",
    "value",
    "Trailing twelve-month earnings as a percentage of price (the inverse of P/E). "
    "Negative earnings are treated as missing rather than as a high yield.",
    unit="%",
)
def earnings_yield(panel: Panel) -> pd.Series:
    return _yield_pct(_col(panel, "pe_ttm"))


@register(
    "book_yield",
    "Book yield",
    "value",
    "Book value per share relative to price (the inverse of P/B). Most meaningful "
    "for asset-heavy businesses and financials.",
    unit="%",
)
def book_yield(panel: Panel) -> pd.Series:
    return _yield_pct(_col(panel, "pb_fy"))


@register(
    "sales_yield",
    "Sales yield",
    "value",
    "Revenue per share relative to price (the inverse of P/S). Useful where "
    "earnings are temporarily depressed or negative.",
    unit="%",
)
def sales_yield(panel: Panel) -> pd.Series:
    return _yield_pct(_col(panel, "ps_ttm"))


@register(
    "fcf_yield",
    "Free cash flow yield",
    "value",
    "Free cash flow relative to price. Harder to manipulate than earnings, "
    "because cash either arrived or it did not.",
    unit="%",
)
def fcf_yield(panel: Panel) -> pd.Series:
    return _yield_pct(_col(panel, "price_to_fcf_fy"))


@register(
    "dividend_yield",
    "Dividend yield",
    "value",
    "Indicated annual dividend as a percentage of price.",
    unit="%",
)
def dividend_yield(panel: Panel) -> pd.Series:
    return _col(panel, "dividend_yield")


@register(
    "peg_inverse",
    "Growth-adjusted value",
    "value",
    "The inverse of the PEG ratio: cheapness relative to the growth being bought. "
    "Higher is better.",
    unit="x",
)
def peg_inverse(panel: Panel) -> pd.Series:
    return inverse(_col(panel, "peg"))


@register(
    "value_vs_own_history",
    "Cheap vs its own history",
    "value",
    "Where today's P/E sits within the stock's own five-year range, as a percentile "
    "inverted so cheap scores high. A bank on 12x looks dear beside a steelmaker on "
    "8x but cheap beside its own five-year median of 18x -- this is the factor that "
    "sees the difference.",
    sector_neutral=False,
    unit="pctile",
)
def value_vs_own_history(panel: Panel) -> pd.Series:
    history = panel.meta.get("valuation_history")
    current = _col(panel, "pe_ttm")
    if not isinstance(history, pd.DataFrame) or history.empty:
        return pd.Series(dtype=float, index=pd.Index(panel.symbols, name="symbol"))

    pe = history[history["metric"] == "pe"]
    if pe.empty:
        return pd.Series(dtype=float, index=pd.Index(panel.symbols, name="symbol"))

    out: dict[str, float] = {}
    for symbol, group in pe.groupby("symbol"):
        values = pd.to_numeric(group["value"], errors="coerce").dropna()
        values = values[values > 0]
        now = current.get(symbol)
        if len(values) < 8 or now is None or not pd.notna(now) or now <= 0:
            continue
        # Percentile of the current multiple within its own history, inverted so
        # that "cheaper than usual" scores high.
        out[symbol] = float(100.0 - (values < now).mean() * 100.0)
    return pd.Series(out, dtype=float).reindex(panel.symbols)


@register(
    "ev_fcf_yield",
    "EV / free cash flow yield",
    "value",
    "Free cash flow against enterprise value, so a debt-laden company does not look "
    "cheap on equity value alone.",
    unit="%",
)
def ev_fcf_yield(panel: Panel) -> pd.Series:
    return _yield_pct(_col(panel, "ev_to_fcf_fy"))


@register(
    "net_cash_to_market_cap",
    "Net cash to market cap",
    "value",
    "Net cash as a share of market capitalisation. Positive values mean the "
    "operating business is being bought for less than the headline price. Not "
    "reported for lenders, whose borrowings are their raw material.",
    unit="%",
)
def net_cash_to_market_cap(panel: Panel) -> pd.Series:
    net_debt = _col(panel, "net_debt_fy")  # rupee million
    market_cap = _col(panel, "market_cap") * CRORE_TO_MILLION  # crore -> million
    ratio = safe_divide(-net_debt, market_cap) * 100.0
    return mask_financials(ratio, panel.sectors)
