from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

UNIVERSE_CSV = DATA_DIR / "universe.csv"
INDEX_TICKER = "^NSEI"

PRICE_PERIOD = "3y"
LOOKBACK_DAYS = 252          # 12-month formation window
SKIP_DAYS = 21                # skip most recent month (short-term reversal)
SHORT_MOM_DAYS = 63            # 3-month momentum
MIN_HISTORY = 300              # minimum trading days required to include a stock
REGIME_SMA_FAST = 50
REGIME_SMA_SLOW = 200

# cache freshness
PRICE_CACHE_TTL_HOURS = 20
FUNDAMENTALS_CACHE_TTL_HOURS = 72

DEFAULT_WEIGHTS = {
    "momentum": 0.30,
    "quality": 0.20,
    "growth": 0.15,
    "value": 0.15,
    "low_vol": 0.20,
}

# Wizard presets: investment horizon -> factor tilt. Short horizons lean on
# momentum/low-vol (price-driven, works over weeks-months); long horizons lean
# on quality/growth/value (fundamentals-driven, needs time to play out) —
# consistent with the standard factor-investing literature (AQR, MSCI) on
# each factor's typical holding-period sensitivity.
HORIZON_WEIGHTS = {
    "short": {"momentum": 0.45, "quality": 0.10, "growth": 0.10, "value": 0.10, "low_vol": 0.25},
    "medium": {"momentum": 0.30, "quality": 0.20, "growth": 0.15, "value": 0.15, "low_vol": 0.20},
    "long": {"momentum": 0.15, "quality": 0.30, "growth": 0.25, "value": 0.25, "low_vol": 0.05},
}

# Screener strategy presets. "weights" strategies route through the classic
# tunable 5-factor blend (factor_mode="all"); "formula" strategies compute
# their own composite score in factors.py (see STRATEGY_FORMULAS) and ignore
# the weights entirely — their factor sliders are hidden in the UI.
STRATEGIES = {
    "momentum_led": {
        "label": "Momentum-led",
        "mode": "weights",
        "weights": HORIZON_WEIGHTS["short"],
        "desc": "Chases price strength & stability. Best for shorter holds, more turnover.",
    },
    "balanced": {
        "label": "Balanced (Classic)",
        "mode": "weights",
        "weights": HORIZON_WEIGHTS["medium"],
        "desc": "An even mix of price trend and fundamentals — the original all-weather default.",
    },
    "fundamentals_led": {
        "label": "Fundamentals-led",
        "mode": "weights",
        "weights": HORIZON_WEIGHTS["long"],
        "desc": "Leans on quality, growth & value. Best for holding through cycles.",
    },
    "quality_compounder": {
        "label": "Quality Compounder",
        "mode": "weights",
        "weights": {"momentum": 0.10, "quality": 0.40, "growth": 0.30, "value": 0.05, "low_vol": 0.15},
        "desc": "AQR-style Quality-Minus-Junk tilt: heavy weight on profitability & growth, minimal weight on classic cheapness. Pay up for durable compounders rather than chase value.",
    },
    "magic_formula": {
        "label": "Magic Formula",
        "mode": "formula",
        "factor_mode": "magic_formula",
        "desc": "Greenblatt's Magic Formula — ranks by earnings yield + return on capital, buys the cheapest, most profitable businesses. (Earnings yield approximated as 1/P-E, return on capital approximated with ROE — this feed doesn't carry EBIT/EV or invested-capital data.)",
    },
    "piotroski": {
        "label": "Piotroski Score",
        "mode": "formula",
        "factor_mode": "piotroski",
        "desc": "A 7-point checklist adapted from Piotroski's F-Score — profitability, leverage & liquidity pass/fail tests. Favors financially healthy businesses over cheap ones.",
    },
    "dual_momentum": {
        "label": "Dual Momentum",
        "mode": "formula",
        "factor_mode": "dual_momentum",
        "desc": "Antonacci's dual momentum — only ranks stocks with positive absolute momentum and an intact uptrend; laggards are pushed to the bottom instead of just underweighted.",
    },
    "graham_defensive": {
        "label": "Graham Defensive",
        "mode": "formula",
        "factor_mode": "graham_defensive",
        "desc": "Benjamin Graham's defensive-investor screen (moderate P/E & P/B, the P/E x P/B <= 22.5 'Graham number', strong liquidity, low debt) blended with the low-volatility factor.",
    },
    "combined": {
        "label": "Combined Consensus",
        "mode": "combined",
        "desc": "Runs every strategy above and keeps only the stocks that rank near the top under all of them — a consensus screen for names multiple independent lenses agree on, rather than any single formula's favorites.",
    },
}

RISK_PROFILE_ADJUSTMENTS = {
    "conservative": {"max_per_sector": 2, "min_liquidity_cr": 10.0, "require_uptrend": True, "low_vol_boost": 0.10},
    "balanced": {"max_per_sector": 3, "min_liquidity_cr": 5.0, "require_uptrend": True, "low_vol_boost": 0.0},
    "aggressive": {"max_per_sector": 4, "min_liquidity_cr": 2.0, "require_uptrend": False, "low_vol_boost": -0.10},
}

DEFAULT_CAPITAL = 200_000
DEFAULT_TOP_N = 10
DEFAULT_MAX_PER_SECTOR = 3
DEFAULT_MIN_LIQUIDITY_CR = 5.0     # min avg daily traded value, INR crore
DEFAULT_MAX_PAIR_CORR = 0.85       # correlation cap for diversification
MAX_SINGLE_WEIGHT = 0.20
MIN_SINGLE_WEIGHT = 0.04
ATR_STOP_MULT = 2.5
ATR_WINDOW = 14
