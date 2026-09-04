"""Nightly factor precomputation.

Factors are never computed in the request path. The web service runs on 512 MB
with roughly a tenth of a CPU, so a screen has to be an indexed SELECT plus a
weighted sum -- not a pandas job over six years of bars. This module does that
work once a night on a real machine and stores the result.

Each factor is scored the same way:

1. compute the raw value from the point-in-time panel
2. winsorize, so one mis-reported ratio cannot dominate the distribution
3. z-score globally, and within sector where the factor is sector-bound
4. flip the sign where a lower raw value is better, so every stored z-score
   reads "higher is better"
5. record percentile and decile, plus how much of the universe was covered
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd
import structlog
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models.factors import FactorCoverage, FactorValue
from app.db.models.fundamentals import ValuationHistory
from app.factors.panel import Panel, build_panel
from app.factors.registry import Factor, all_factors
from app.factors.stats import (
    blended_zscore,
    deciles,
    percentile_rank,
    winsorize,
    zscore,
)

log = structlog.get_logger(__name__)

# Below this, a factor's cross-sectional scores are noise rather than signal.
MIN_COVERAGE_PCT = 20.0


def score_factor(factor: Factor, raw: pd.Series, panel: Panel) -> pd.DataFrame:
    """Turn raw factor values into comparable, signed scores."""
    raw = pd.to_numeric(raw, errors="coerce").reindex(panel.symbols)

    # Sign flip first, so every downstream statistic reads higher-is-better.
    oriented = raw if factor.higher_is_better else -raw
    clipped = winsorize(oriented)

    global_z = zscore(clipped)
    sector_z = blended_zscore(clipped, panel.sectors) if factor.sector_neutral else global_z

    missing = raw.isna()
    return pd.DataFrame(
        {
            "raw": raw,
            "zscore": global_z.mask(missing),
            "sector_zscore": sector_z.mask(missing),
            "percentile": percentile_rank(clipped),
            "decile": deciles(clipped),
        }
    )


def _load_valuation_history(db: Session, symbols: list[str], as_of: dt.date) -> pd.DataFrame:
    from sqlalchemy import select

    rows = db.execute(
        select(
            ValuationHistory.symbol,
            ValuationHistory.date,
            ValuationHistory.metric,
            ValuationHistory.value,
        ).where(
            ValuationHistory.symbol.in_(symbols),
            ValuationHistory.date <= as_of,
        )
    ).all()
    return pd.DataFrame(rows, columns=["symbol", "date", "metric", "value"])


def precompute_factors(
    db: Session,
    symbols: list[str],
    *,
    as_of: dt.date | None = None,
    replace: bool = True,
) -> dict[str, Any]:
    as_of = as_of or dt.date.today()
    symbols = sorted(set(symbols))
    if not symbols:
        return {"rows": 0, "factors": 0, "note": "no symbols"}

    panel = build_panel(db, symbols, as_of)
    panel.meta["valuation_history"] = _load_valuation_history(db, symbols, as_of)

    registry = all_factors()
    total = len(symbols)
    rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    low_coverage: list[str] = []
    failed: list[str] = []

    for name, factor in registry.items():
        try:
            raw = factor.compute(panel)
        except Exception as exc:
            log.error("factors.compute_failed", factor=name, error=str(exc)[:250])
            failed.append(name)
            continue

        scored = score_factor(factor, raw, panel)
        covered = int(scored["raw"].notna().sum())
        coverage_pct = round(100 * covered / total, 1) if total else 0.0

        coverage_rows.append(
            {
                "as_of": as_of,
                "factor": name,
                "n_total": total,
                "n_covered": covered,
                "coverage_pct": coverage_pct,
            }
        )
        if coverage_pct < MIN_COVERAGE_PCT:
            low_coverage.append(name)

        for symbol, row in scored.iterrows():
            if pd.isna(row["raw"]):
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "as_of": as_of,
                    "factor": name,
                    "raw": _clean(row["raw"]),
                    "zscore": _clean(row["zscore"]),
                    "sector_zscore": _clean(row["sector_zscore"]),
                    "percentile": _clean(row["percentile"]),
                    "decile": None if pd.isna(row["decile"]) else int(row["decile"]),
                    "estimated": False,
                }
            )

    if replace:
        db.execute(delete(FactorValue).where(FactorValue.as_of == as_of))
        db.execute(delete(FactorCoverage).where(FactorCoverage.as_of == as_of))

    for i in range(0, len(rows), 1000):
        chunk = rows[i : i + 1000]
        stmt = pg_insert(FactorValue).values(chunk)
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["symbol", "as_of", "factor"],
                set_={
                    c: stmt.excluded[c]
                    for c in ("raw", "zscore", "sector_zscore", "percentile", "decile")
                },
            )
        )
    if coverage_rows:
        stmt = pg_insert(FactorCoverage).values(coverage_rows)
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["as_of", "factor"],
                set_={
                    "n_total": stmt.excluded.n_total,
                    "n_covered": stmt.excluded.n_covered,
                    "coverage_pct": stmt.excluded.coverage_pct,
                },
            )
        )
    db.commit()

    log.info(
        "factors.precomputed",
        as_of=str(as_of),
        rows=len(rows),
        factors=len(registry) - len(failed),
        low_coverage=len(low_coverage),
    )
    return {
        "rows": len(rows),
        "factors": len(registry) - len(failed),
        "symbols": total,
        "low_coverage": low_coverage,
        "failed": failed,
    }


def _clean(value: Any) -> float | None:
    """NaN and infinity are not valid JSON or valid float columns."""
    if value is None or pd.isna(value):
        return None
    number = float(value)
    if number in (float("inf"), float("-inf")):
        return None
    return number
