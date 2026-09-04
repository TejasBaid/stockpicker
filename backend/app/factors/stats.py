"""Cross-sectional statistics shared by every factor.

Ported from the prototype's factor library, which got these right:

* **Winsorize then z-score.** A single mis-reported ratio (a P/E of 12,000
  after a near-zero earnings quarter) otherwise drags the whole distribution.
* **Sector-blended scoring.** Pure global z-scoring lets one hot sector fill
  every slot; pure within-sector scoring promotes the best of a bad sector.
  Blending keeps cross-sector comparability while still rewarding relative
  strength inside a sector.
* **Median-fill, don't drop.** Dropping names with a missing input
  systematically penalises smaller companies with sparser coverage, which
  quietly biases the whole screen toward large caps.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_CLIP = 3.0
DEFAULT_SECTOR_WEIGHT = 0.5
MIN_OBSERVATIONS = 3


def winsorize(series: pd.Series, lower: float = 0.02, upper: float = 0.98) -> pd.Series:
    s = series.astype(float)
    valid = s.dropna()
    if len(valid) < MIN_OBSERVATIONS:
        return s
    lo, hi = valid.quantile(lower), valid.quantile(upper)
    if not np.isfinite(lo) or not np.isfinite(hi) or lo >= hi:
        return s
    return s.clip(lo, hi)


def zscore(series: pd.Series, clip: float = DEFAULT_CLIP) -> pd.Series:
    """Standardise, returning zeros when there is nothing to standardise
    against -- a degenerate distribution should not silently become extreme."""
    s = series.astype(float)
    valid = s.dropna()
    if len(valid) < MIN_OBSERVATIONS or valid.std(ddof=0) == 0:
        return pd.Series(0.0, index=series.index, dtype=float)
    z = (s - valid.mean()) / valid.std(ddof=0)
    return z.clip(-clip, clip)


def sector_zscore(series: pd.Series, sectors: pd.Series) -> pd.Series:
    """Z-score within each sector, falling back to the global score for
    sectors too small to standardise."""
    sec = sectors.reindex(series.index).fillna("Unknown")
    out = pd.Series(np.nan, index=series.index, dtype=float)
    global_z = zscore(series)
    for _name, group in series.groupby(sec):
        if len(group.dropna()) >= MIN_OBSERVATIONS:
            out.loc[group.index] = zscore(group)
        else:
            out.loc[group.index] = global_z.loc[group.index]
    return out.fillna(0.0)


def blended_zscore(
    series: pd.Series, sectors: pd.Series, sector_weight: float = DEFAULT_SECTOR_WEIGHT
) -> pd.Series:
    g = zscore(series)
    w = sector_zscore(series, sectors)
    return (1 - sector_weight) * g + sector_weight * w


def fill_median(series: pd.Series) -> pd.Series:
    median = series.median(skipna=True)
    return series.fillna(median if pd.notna(median) else 0.0)


def percentile_rank(series: pd.Series) -> pd.Series:
    """0-100, higher is better. NaNs stay NaN so coverage is measurable."""
    return series.rank(pct=True, na_option="keep") * 100.0


def deciles(series: pd.Series) -> pd.Series:
    """1 (best) to 10 (worst) on a higher-is-better input."""
    ranked = series.rank(ascending=False, na_option="keep")
    n = int(ranked.notna().sum())
    if n == 0:
        return pd.Series(np.nan, index=series.index, dtype=float)
    return np.ceil(ranked / n * 10).clip(1, 10)


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Element-wise division that yields NaN rather than inf on a zero or
    negative denominator, so a zero-equity company cannot produce an
    astronomical ratio that then dominates the ranking."""
    den = denominator.astype(float).replace(0.0, np.nan)
    return numerator.astype(float) / den


def inverse(series: pd.Series) -> pd.Series:
    """Reciprocal for building yields from multiples (earnings yield from P/E).

    Non-positive multiples become NaN: a negative P/E is not "cheap", and
    treating it as a large yield inverts the factor's meaning.
    """
    s = series.astype(float)
    s = s.where(s > 0)
    return 1.0 / s


# Lenders' balance sheets are structurally different: borrowings are their raw
# material, not leverage, and interest is a cost of goods rather than a
# financing burden. Factors built on that distinction are not merely extreme
# for financials, they are meaningless, so they are masked rather than
# winsorized into a misleading middle.
FINANCIAL_SECTOR_MARKERS = ("financial", "bank", "insurance", "nbfc")


def mask_financials(series: pd.Series, sectors: pd.Series) -> pd.Series:
    sec = sectors.reindex(series.index).fillna("").astype(str).str.lower()
    is_financial = sec.apply(lambda s: any(m in s for m in FINANCIAL_SECTOR_MARKERS))
    return series.mask(is_financial)
