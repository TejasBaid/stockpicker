"""Factor engines: momentum, quality, growth, value, low-volatility.

Improvements over a naive single-factor screen:
  - risk-adjusted, skip-month momentum blended with short-term trend
  - sector-relative z-scoring blended with global z-scoring, so the
    composite doesn't just reward whichever sector is hot
  - a dedicated growth factor (revenue/earnings growth) separate from
    quality (profitability/leverage), since a stock can be high-quality
    but not growing, or growing but low-quality
  - explicit liquidity and trend (price > 200 SMA) gates applied before
    ranking, so illiquid or structurally-downtrending names never surface
  - missing data is median-filled per factor rather than silently
    dropping the stock (dropping systematically penalizes small/mid caps
    with sparser fundamentals coverage)

Beyond the tunable 5-factor blend ("classic"), this module also exposes a
handful of named strategies with their own composite formula rather than a
weighted sum of the same five z-scores — see STRATEGY_FORMULAS and each
factor_* function's docstring for the literature it's adapted from and the
approximations made where this feed lacks the original data (EBIT/EV,
invested capital, year-over-year statement deltas).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from . import config


def zscore(series: pd.Series, clip: float = 3.0) -> pd.Series:
    s = series.astype(float)
    valid = s.dropna()
    if len(valid) < 3 or valid.std(ddof=0) == 0:
        return pd.Series(0.0, index=series.index)
    z = (s - valid.mean()) / valid.std(ddof=0)
    return z.clip(-clip, clip)


def sector_blend_zscore(series: pd.Series, sectors: pd.Series, global_weight: float = 0.5) -> pd.Series:
    """Blend a global z-score with a within-sector z-score.

    Pure global z-scoring lets one hot sector dominate every slot; pure
    sector-relative scoring can promote the "best of a bad sector". The
    blend keeps cross-sector comparability while still rewarding relative
    strength inside a sector.
    """
    g = zscore(series)
    sec = sectors.reindex(series.index).fillna("Unknown")
    within = series.groupby(sec).transform(lambda s: zscore(s))
    within = within.fillna(0.0)
    return global_weight * g + (1 - global_weight) * within


def _fill_median(s: pd.Series) -> pd.Series:
    med = s.median(skipna=True)
    return s.fillna(med if pd.notna(med) else 0.0)


def factor_momentum(prices: pd.DataFrame) -> pd.Series:
    lb, sk, sh = config.LOOKBACK_DAYS, config.SKIP_DAYS, config.SHORT_MOM_DAYS
    if len(prices) < lb + 5:
        return pd.Series(dtype=float)

    p_now = prices.iloc[-1]
    p_skip = prices.iloc[-(sk + 1)]
    p_12m = prices.iloc[-(lb + 1)]
    p_3m = prices.iloc[-(sh + 1)]

    mom_12_1 = (p_skip / p_12m) - 1
    mom_3 = (p_now / p_3m) - 1

    daily_ret = prices.iloc[-lb:].pct_change()
    ann_vol = daily_ret.std() * np.sqrt(252)
    risk_adj_mom = mom_12_1 / ann_vol.replace(0, np.nan)

    blended = 0.70 * zscore(risk_adj_mom) + 0.30 * zscore(mom_3)
    return zscore(blended)


def factor_quality(fundamentals: pd.DataFrame, sectors: pd.Series) -> pd.Series:
    df = fundamentals.copy()
    roe_z = sector_blend_zscore(_fill_median(df["roe"]), sectors)
    margin_z = sector_blend_zscore(_fill_median(df["profit_margin"]), sectors)
    debt_z = -sector_blend_zscore(_fill_median(df["debt_equity"]), sectors)
    cr = df["current_ratio"].clip(upper=3)
    cr_z = sector_blend_zscore(_fill_median(cr), sectors)

    quality = 0.35 * roe_z + 0.30 * margin_z + 0.25 * debt_z + 0.10 * cr_z
    return zscore(quality)


def factor_growth(fundamentals: pd.DataFrame, sectors: pd.Series) -> pd.Series:
    df = fundamentals.copy()
    rev_g = _fill_median(df["revenue_growth"].clip(-1, 3))
    earn_g = _fill_median(df["earnings_growth"].clip(-2, 5))
    growth = 0.55 * sector_blend_zscore(rev_g, sectors) + 0.45 * sector_blend_zscore(earn_g, sectors)
    return zscore(growth)


def factor_value(fundamentals: pd.DataFrame, sectors: pd.Series) -> pd.Series:
    df = fundamentals.copy()
    ey = (1 / df["pe"]).where(df["pe"] > 0)
    ey_z = sector_blend_zscore(_fill_median(ey), sectors)
    pb_z = -sector_blend_zscore(_fill_median(df["pb"].clip(lower=0.1)), sectors)
    value = 0.60 * ey_z + 0.40 * pb_z
    return zscore(value)


def factor_low_volatility(prices: pd.DataFrame) -> pd.Series:
    if len(prices) < config.LOOKBACK_DAYS:
        return pd.Series(dtype=float)

    daily_ret = prices.iloc[-config.LOOKBACK_DAYS:].pct_change()
    ann_vol = daily_ret.std() * np.sqrt(252)
    vol_z = -zscore(ann_vol)

    combined = vol_z
    if config.INDEX_TICKER in daily_ret.columns:
        idx_ret = daily_ret[config.INDEX_TICKER].dropna()
        stock_ret = daily_ret.drop(columns=[config.INDEX_TICKER], errors="ignore")
        betas = {}
        for col in stock_ret.columns:
            s = stock_ret[col].dropna()
            aligned = pd.concat([s, idx_ret], axis=1).dropna()
            if len(aligned) > 60:
                b, _, _, _, _ = stats.linregress(aligned.iloc[:, 1], aligned.iloc[:, 0])
                betas[col] = b
        if betas:
            beta_series = pd.Series(betas)
            beta_z = -zscore(beta_series)
            combined = 0.60 * vol_z + 0.40 * beta_z.reindex(vol_z.index).fillna(0.0)

    return zscore(combined)


def liquidity_value_cr(prices: pd.DataFrame, volumes: pd.DataFrame, window: int = 20) -> pd.Series:
    """Average daily traded value (INR crore) over the trailing window."""
    px = prices.iloc[-window:]
    vol = volumes.reindex(index=px.index, columns=px.columns)
    turnover = (px * vol).mean()
    return turnover / 1e7  # crore


def trend_qualifier(prices: pd.DataFrame) -> pd.Series:
    """True if price is above its 200-day SMA (structural uptrend gate)."""
    sma200 = prices.rolling(config.REGIME_SMA_SLOW).mean().iloc[-1]
    return prices.iloc[-1] > sma200


def atr_stop_levels(prices: pd.DataFrame, mult: float = None, window: int = None) -> pd.Series:
    """Approximate ATR (using close-to-close range as a proxy, since we only
    have adjusted close) and a suggested trailing-stop distance below price.
    """
    mult = mult or config.ATR_STOP_MULT
    window = window or config.ATR_WINDOW
    daily_range = prices.diff().abs()
    atr = daily_range.rolling(window).mean().iloc[-1]
    last_px = prices.iloc[-1]
    stop_price = last_px - mult * atr
    return stop_price.clip(lower=0)


def factor_magic_formula(fundamentals: pd.DataFrame, sectors: pd.Series) -> pd.Series:
    """Greenblatt's Magic Formula: rank by earnings yield + return on capital.

    The original formula uses EY = EBIT / enterprise value and
    ROC = EBIT / (net working capital + net fixed assets); this feed only
    carries trailing P/E and ROE, so EY is approximated as 1/PE and ROC as
    ROE. Both track the originals closely for ordinary, non-distressed,
    non-financial businesses, which is Greenblatt's own caveat for using
    the simplified ratios.
    """
    df = fundamentals.copy()
    ey = (1 / df["pe"]).where(df["pe"] > 0)
    roc = df["roe"]
    ey_rank = ey.rank(ascending=False, na_option="bottom")
    roc_rank = roc.rank(ascending=False, na_option="bottom")
    combined_rank = ey_rank + roc_rank
    return zscore(-combined_rank)


def factor_piotroski(fundamentals: pd.DataFrame, sectors: pd.Series) -> pd.Series:
    """Adapted Piotroski F-Score: seven pass/fail fundamental-health tests.

    The original 9-point F-Score scores year-over-year statement deltas
    (change in ROA, CFO vs. accruals, change in leverage/liquidity/margin/
    turnover) that this feed doesn't carry — only a single latest snapshot
    per stock. This keeps the spirit (profitability, leverage, liquidity,
    efficiency) using what's available instead of the original deltas.
    """
    df = fundamentals.copy()
    sec = sectors.reindex(df.index).fillna("Unknown")
    debt_equity_sector_median = df["debt_equity"].groupby(sec).transform("median")

    tests = pd.DataFrame({
        "roe_positive": df["roe"] > 0,
        "margin_positive": df["profit_margin"] > 0,
        "revenue_growing": df["revenue_growth"] > 0,
        "earnings_growing": df["earnings_growth"] > 0,
        "below_sector_leverage": df["debt_equity"] < debt_equity_sector_median,
        "healthy_liquidity": df["current_ratio"] >= 1.5,
        "earnings_outpace_revenue": df["earnings_growth"] >= df["revenue_growth"],
    })
    score = tests.sum(axis=1)
    return zscore(score)


def factor_dual_momentum(prices: pd.DataFrame) -> pd.Series:
    """Antonacci-style dual momentum: relative strength gated by absolute momentum.

    Relative momentum ranks stocks by the same 12-1 momentum used
    elsewhere; absolute momentum requires the stock's own trailing return
    to be positive AND price above its 200-day average (Antonacci gates
    against a T-bill hurdle for asset allocation — for single stocks, own
    trailing return plus a trend filter is the standard adaptation). Names
    failing the absolute test are pushed to the bottom of the ranking
    rather than merely down-weighted, so laggards are effectively sat out.
    """
    lb, sk = config.LOOKBACK_DAYS, config.SKIP_DAYS
    if len(prices) < lb + 5:
        return pd.Series(dtype=float)

    p_skip = prices.iloc[-(sk + 1)]
    p_12m = prices.iloc[-(lb + 1)]
    mom_12_1 = (p_skip / p_12m) - 1

    sma200 = prices.rolling(config.REGIME_SMA_SLOW).mean().iloc[-1]
    above_sma = (prices.iloc[-1] > sma200).reindex(mom_12_1.index).fillna(False)
    absolute_ok = (mom_12_1 > 0) & above_sma

    relative = zscore(mom_12_1)
    return relative.where(absolute_ok, -3.0)


def factor_graham_defensive(prices: pd.DataFrame, fundamentals: pd.DataFrame, sectors: pd.Series) -> pd.Series:
    """Benjamin Graham's defensive-investor screen blended with low-volatility.

    Graham's 1949 criteria, adapted to available fields: moderate P/E,
    moderate P/B, the classic P/E x P/B <= 22.5 "Graham number", a current
    ratio >= 2, positive earnings growth, and below-sector debt. Blended
    50/50 with the low-volatility factor, since Graham's "margin of safety"
    and the modern low-volatility anomaly both select the same kind of
    defensive stock.
    """
    df = fundamentals.copy()
    sec = sectors.reindex(df.index).fillna("Unknown")
    debt_equity_sector_median = df["debt_equity"].groupby(sec).transform("median")
    pe, pb = df["pe"], df["pb"]

    tests = pd.DataFrame({
        "moderate_pe": pe.between(0, 20),
        "moderate_pb": pb.between(0, 3),
        "graham_number": (pe * pb) <= 22.5,
        "strong_liquidity": df["current_ratio"] >= 2,
        "earnings_growing": df["earnings_growth"] > 0,
        "below_sector_debt": df["debt_equity"] < debt_equity_sector_median,
    })
    graham_z = zscore(tests.sum(axis=1))
    vol_z = factor_low_volatility(prices).reindex(graham_z.index).fillna(0.0)
    return zscore(0.5 * graham_z + 0.5 * vol_z)


STRATEGY_FORMULAS = {
    "magic_formula": lambda prices, fundamentals, sectors: factor_magic_formula(fundamentals, sectors),
    "piotroski": lambda prices, fundamentals, sectors: factor_piotroski(fundamentals, sectors),
    "dual_momentum": lambda prices, fundamentals, sectors: factor_dual_momentum(
        prices.drop(columns=[config.INDEX_TICKER], errors="ignore")
    ),
    "graham_defensive": lambda prices, fundamentals, sectors: factor_graham_defensive(prices, fundamentals, sectors),
}


def build_scores(
    prices: pd.DataFrame,
    fundamentals: pd.DataFrame,
    weights: dict,
    factor_mode: str = "all",
) -> pd.DataFrame:
    stock_prices = prices.drop(columns=[config.INDEX_TICKER], errors="ignore")
    sectors = fundamentals["sector"].fillna("Unknown") if "sector" in fundamentals.columns else pd.Series("Unknown", index=stock_prices.columns)

    f_mom = factor_momentum(stock_prices)
    f_vol = factor_low_volatility(prices)
    f_qual = factor_quality(fundamentals, sectors) if not fundamentals.empty else pd.Series(dtype=float)
    f_growth = factor_growth(fundamentals, sectors) if not fundamentals.empty else pd.Series(dtype=float)
    f_val = factor_value(fundamentals, sectors) if not fundamentals.empty else pd.Series(dtype=float)

    idx = f_mom.index
    scores = pd.DataFrame({
        "momentum": f_mom,
        "quality": f_qual.reindex(idx),
        "growth": f_growth.reindex(idx),
        "value": f_val.reindex(idx),
        "low_vol": f_vol.reindex(idx),
    })

    if factor_mode in STRATEGY_FORMULAS and not fundamentals.empty:
        scores["composite"] = STRATEGY_FORMULAS[factor_mode](prices, fundamentals, sectors).reindex(idx).fillna(-3.0)
    elif factor_mode != "all" and factor_mode in scores.columns:
        scores["composite"] = scores[factor_mode].fillna(0)
    else:
        w = weights
        total_w = sum(w.values()) or 1.0
        scores["composite"] = sum(
            (w.get(f, 0) / total_w) * scores[f].fillna(0) for f in ["momentum", "quality", "growth", "value", "low_vol"]
        )

    return scores
