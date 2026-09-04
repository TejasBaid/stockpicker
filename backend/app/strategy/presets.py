"""Built-in strategies.

Each is a weighting over registered factors, with optional gates. They are
starting points and a demonstration of the vocabulary -- the point of the
platform is that you write your own.
"""

from __future__ import annotations

from typing import Any

# Liquidity is gated on almost everything: a wonderful business you cannot buy
# is not an idea, and thin names dominate naive factor screens.
_LIQUID = {"factor": "liquidity", "op": "gte", "value": 5.0}

PRESETS: dict[str, dict[str, Any]] = {
    "quality_value": {
        "name": "Quality at a price",
        "description": (
            "Profitable, conservatively financed businesses trading on modest "
            "multiples. The core long-term screen."
        ),
        "weights": {
            "roce": 0.20,
            "roe": 0.15,
            "earnings_yield": 0.20,
            "fcf_yield": 0.15,
            "low_leverage": 0.15,
            "cash_conversion": 0.15,
        },
        "filters": [_LIQUID, {"factor": "roe", "op": "gte", "value": 10.0}],
    },
    "momentum": {
        "name": "Momentum",
        "description": (
            "Names in established uptrends, risk-adjusted so a steady climb "
            "outranks the same return delivered by one violent gap."
        ),
        "weights": {
            "risk_adjusted_momentum": 0.30,
            "momentum_12_1": 0.25,
            "near_52w_high": 0.20,
            "relative_strength": 0.15,
            "trend_strength": 0.10,
        },
        "filters": [_LIQUID, {"factor": "trend_strength", "op": "gt", "value": 0.0}],
    },
    "earnings_revision": {
        "name": "Earnings revisions",
        "description": (
            "Companies where analyst expectations are being revised upward and "
            "recent results beat consensus. The shortest-horizon edge here."
        ),
        "weights": {
            "rating_revision": 0.30,
            "earnings_surprise": 0.30,
            "target_upside": 0.20,
            "eps_growth_ttm": 0.20,
        },
        "filters": [_LIQUID],
    },
    "compounder": {
        "name": "Compounders",
        "description": (
            "High returns on capital, growing steadily, converting profit into "
            "cash, with promoters holding a real stake. Built to be held."
        ),
        "weights": {
            "roce": 0.20,
            "revenue_growth_5y": 0.15,
            "eps_growth_5y": 0.15,
            "cash_conversion": 0.15,
            "margin_stability": 0.10,
            "low_leverage": 0.10,
            "promoter_skin_in_the_game": 0.05,
            "piotroski_f_score": 0.10,
        },
        "filters": [_LIQUID, {"factor": "roce", "op": "gte", "value": 12.0}],
    },
    "deep_value": {
        "name": "Deep value",
        "description": (
            "The cheapest names on multiple measures, screened for financial "
            "strength so cheapness is not simply distress."
        ),
        "weights": {
            "earnings_yield": 0.25,
            "book_yield": 0.20,
            "value_vs_own_history": 0.20,
            "fcf_yield": 0.15,
            "piotroski_f_score": 0.20,
        },
        "filters": [_LIQUID, {"factor": "piotroski_f_score", "op": "gte", "value": 5.0}],
    },
    "quality_momentum": {
        "name": "Quality momentum",
        "description": (
            "Good businesses that the market has started to notice. Combining "
            "the two is historically more durable than either alone."
        ),
        "weights": {
            "roce": 0.20,
            "cash_conversion": 0.10,
            "low_leverage": 0.10,
            "risk_adjusted_momentum": 0.25,
            "near_52w_high": 0.15,
            "rating_revision": 0.20,
        },
        "filters": [_LIQUID],
    },
    "low_volatility": {
        "name": "Low volatility",
        "description": (
            "Steady, low-beta, shallow-drawdown names with sound fundamentals. "
            "For capital you would rather not watch."
        ),
        "weights": {
            "low_volatility": 0.30,
            "low_drawdown": 0.20,
            "low_beta": 0.15,
            "roe": 0.15,
            "low_leverage": 0.10,
            "dividend_yield": 0.10,
        },
        "filters": [_LIQUID],
    },
    "institutional_flow": {
        "name": "Institutional accumulation",
        "description": (
            "Where foreign and domestic institutions have been adding, with "
            "fundamentals to justify it."
        ),
        "weights": {
            "fii_accumulation": 0.25,
            "mf_accumulation": 0.20,
            "rating_revision": 0.15,
            "roce": 0.20,
            "revenue_growth_ttm": 0.20,
        },
        "filters": [_LIQUID],
    },
}


def preset(slug: str) -> dict[str, Any]:
    if slug not in PRESETS:
        raise KeyError(f"Unknown strategy: {slug}")
    return PRESETS[slug]
