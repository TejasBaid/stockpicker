"""The statistical primitives every factor is built on."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.factors.stats import (
    blended_zscore,
    deciles,
    fill_median,
    inverse,
    percentile_rank,
    safe_divide,
    sector_zscore,
    winsorize,
    zscore,
)


def test_zscore_standardises() -> None:
    z = zscore(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0]))
    assert z.mean() == pytest.approx(0.0, abs=1e-9)
    assert z.std(ddof=0) == pytest.approx(1.0, abs=1e-9)


def test_zscore_is_flat_when_there_is_nothing_to_compare() -> None:
    assert (zscore(pd.Series([5.0, 5.0, 5.0])) == 0).all()
    assert (zscore(pd.Series([1.0, 2.0])) == 0).all()  # below the minimum count


def test_zscore_clips_outliers() -> None:
    z = zscore(pd.Series([1.0, 1.0, 1.0, 1.0, 1000.0]))
    assert z.max() <= 3.0


def test_zscore_preserves_nans() -> None:
    z = zscore(pd.Series([1.0, 2.0, 3.0, np.nan]))
    assert np.isnan(z.iloc[3])


def test_winsorize_pulls_in_the_tails_without_reordering() -> None:
    s = pd.Series([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10_000])
    w = winsorize(s)
    assert w.max() < 10_000
    assert w.is_monotonic_increasing


def test_sector_zscore_scores_within_each_sector() -> None:
    values = pd.Series([1.0, 2, 3, 10, 20, 30], index=list("abcdef"))
    sectors = pd.Series(["X"] * 3 + ["Y"] * 3, index=list("abcdef"))
    z = sector_zscore(values, sectors)
    # The worst of each sector scores the same despite very different levels.
    assert z["a"] == pytest.approx(z["d"])
    assert z["c"] == pytest.approx(z["f"])


def test_sector_zscore_falls_back_for_tiny_sectors() -> None:
    values = pd.Series([1.0, 2, 3, 4, 99], index=list("abcde"))
    sectors = pd.Series(["X", "X", "X", "X", "Solo"], index=list("abcde"))
    z = sector_zscore(values, sectors)
    assert np.isfinite(z["e"])  # the lone member uses the global score


def test_blended_zscore_sits_between_its_two_inputs() -> None:
    values = pd.Series([1.0, 2, 3, 10, 20, 30], index=list("abcdef"))
    sectors = pd.Series(["X"] * 3 + ["Y"] * 3, index=list("abcdef"))
    g, w = zscore(values), sector_zscore(values, sectors)
    b = blended_zscore(values, sectors, sector_weight=0.5)
    for i in values.index:
        assert min(g[i], w[i]) - 1e-9 <= b[i] <= max(g[i], w[i]) + 1e-9


def test_fill_median_does_not_penalise_sparse_coverage() -> None:
    filled = fill_median(pd.Series([1.0, 2.0, 3.0, np.nan]))
    assert filled.iloc[3] == 2.0
    assert filled.notna().all()


def test_inverse_treats_negative_multiples_as_missing() -> None:
    """A negative P/E is not a high earnings yield -- it is no signal at all."""
    out = inverse(pd.Series([10.0, -5.0, 0.0, 4.0]))
    assert out.iloc[0] == pytest.approx(0.1)
    assert np.isnan(out.iloc[1])
    assert np.isnan(out.iloc[2])
    assert out.iloc[3] == pytest.approx(0.25)


def test_safe_divide_never_returns_infinity() -> None:
    out = safe_divide(pd.Series([1.0, 2.0]), pd.Series([0.0, 4.0]))
    assert np.isnan(out.iloc[0])
    assert out.iloc[1] == pytest.approx(0.5)


def test_deciles_rank_best_first() -> None:
    d = deciles(pd.Series(range(100), dtype=float))
    assert d.iloc[99] == 1  # highest value -> best decile
    assert d.iloc[0] == 10
    assert d.min() >= 1 and d.max() <= 10


def test_percentile_rank_keeps_missing_values_missing() -> None:
    p = percentile_rank(pd.Series([1.0, 2.0, np.nan, 4.0]))
    assert np.isnan(p.iloc[2])
    assert p.iloc[3] == pytest.approx(100.0)


def test_net_cash_factor_uses_consistent_units() -> None:
    """Regression: the vendor reports market cap in rupee crore but statement
    figures in rupee million. Mixing them made this factor wrong by 10x, which
    showed up as net cash positions of several thousand percent."""
    import pandas as pd

    from app.factors.panel import Panel
    from app.factors.value import net_cash_to_market_cap

    panel = Panel(
        as_of=__import__("datetime").date(2026, 1, 1),
        symbols=["TCS"],
        sectors=pd.Series({"TCS": "IT"}),
        names=pd.Series({"TCS": "TCS"}),
        prices=pd.DataFrame(),
        volumes=pd.DataFrame(),
        highs=pd.DataFrame(),
        lows=pd.DataFrame(),
        benchmark=pd.Series(dtype=float),
        # Real TCS figures: market cap Rs 848,442 crore, net cash Rs 32,664 crore.
        fundamentals=pd.DataFrame(
            {"market_cap": [848_442.0], "net_debt_fy": [-326_640.0]}, index=["TCS"]
        ),
        statements=pd.DataFrame(),
        estimates=pd.DataFrame(),
        targets=pd.DataFrame(),
        shareholding=pd.DataFrame(),
    )
    value = float(net_cash_to_market_cap(panel).iloc[0])
    assert 3.0 < value < 5.0, f"expected ~3.9% net cash, got {value:.1f}%"
