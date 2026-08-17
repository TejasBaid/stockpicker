from __future__ import annotations

import numpy as np
import pandas as pd

from . import config


def detect_regime(index_prices: pd.Series) -> dict:
    """Three-state market regime filter using dual SMA crossover + trend slope."""
    sma_slow = index_prices.rolling(config.REGIME_SMA_SLOW).mean().iloc[-1]
    sma_fast = index_prices.rolling(config.REGIME_SMA_FAST).mean().iloc[-1]
    current = index_prices.iloc[-1]

    ret_1m = (current / index_prices.iloc[-22]) - 1
    ret_3m = (current / index_prices.iloc[-63]) - 1
    idx_vol = index_prices.pct_change().iloc[-63:].std() * np.sqrt(252)

    above_slow = current > sma_slow
    above_fast = current > sma_fast
    golden_cross = sma_fast > sma_slow

    if above_slow and above_fast and golden_cross:
        state, deploy_pct = "GREEN", 1.00
    elif above_slow and not above_fast:
        state, deploy_pct = "YELLOW", 0.65
    else:
        state, deploy_pct = "RED", 0.25

    return {
        "state": state,
        "deploy_pct": deploy_pct,
        "current": float(current),
        "sma_fast": float(sma_fast),
        "sma_slow": float(sma_slow),
        "ret_1m": float(ret_1m),
        "ret_3m": float(ret_3m),
        "idx_vol": float(idx_vol),
        "above_slow": bool(above_slow),
        "golden_cross": bool(golden_cross),
    }
