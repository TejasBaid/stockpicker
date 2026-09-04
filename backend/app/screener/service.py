"""The screener.

Deliberately a database query, not a computation. Factor values are precomputed
nightly, so ranking the Nifty 200 is an indexed read plus a weighted sum over a
few thousand rows -- which is what makes it viable on a free-tier instance.

Weights are expressed against factor *names*; a strategy is just a mapping of
name to weight plus optional filters.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd
from sqlalchemy import Row, func, select
from sqlalchemy.orm import Session

from app.core.errors import DataUnavailableError
from app.db.models.factors import FactorCoverage, FactorValue
from app.db.models.market import Instrument, Universe, UniverseMember
from app.factors.registry import all_factors

ScoreBasis = Literal["zscore", "sector_zscore"]

DEFAULT_UNIVERSE = "nifty200"


@dataclass
class Filter:
    """A gate applied before ranking, expressed on a factor's raw value."""

    factor: str
    op: Literal["gt", "gte", "lt", "lte"]
    value: float

    def passes(self, raw: float | None) -> bool:
        if raw is None or pd.isna(raw):
            # Missing data must not silently pass a gate.
            return False
        match self.op:
            case "gt":
                return raw > self.value
            case "gte":
                return raw >= self.value
            case "lt":
                return raw < self.value
            case "lte":
                return raw <= self.value
        return False


@dataclass
class ScreenRequest:
    weights: dict[str, float]
    universe: str = DEFAULT_UNIVERSE
    filters: list[Filter] = field(default_factory=list)
    limit: int = 25
    max_per_sector: int | None = None
    basis: ScoreBasis = "sector_zscore"
    as_of: dt.date | None = None
    symbols: list[str] | None = None


def latest_as_of(db: Session) -> dt.date | None:
    return db.scalar(select(func.max(FactorValue.as_of)))


def universe_members(db: Session, slug: str) -> list[str]:
    return list(
        db.scalars(
            select(UniverseMember.symbol)
            .join(Universe, Universe.id == UniverseMember.universe_id)
            .where(Universe.slug == slug)
        ).all()
    )


def _factor_frame(
    db: Session, as_of: dt.date, symbols: list[str], factors: list[str]
) -> pd.DataFrame:
    """Only the factors this screen actually uses.

    Fetching all 48 for 200 symbols is ~8,000 rows and dominates the request;
    a typical strategy touches six or seven.
    """
    rows: Sequence[Row[Any]] = db.execute(
        select(
            FactorValue.symbol,
            FactorValue.factor,
            FactorValue.raw,
            FactorValue.zscore,
            FactorValue.sector_zscore,
            FactorValue.percentile,
            FactorValue.decile,
        ).where(
            FactorValue.as_of == as_of,
            FactorValue.symbol.in_(symbols),
            FactorValue.factor.in_(factors),
        )
    ).all()
    return pd.DataFrame(
        rows,
        columns=["symbol", "factor", "raw", "zscore", "sector_zscore", "percentile", "decile"],
    )


def run_screen(db: Session, request: ScreenRequest) -> dict[str, Any]:
    as_of = request.as_of or latest_as_of(db)
    if as_of is None:
        raise DataUnavailableError(
            "No factor data yet. Run `python -m app.ingest.jobs factors` first."
        )

    symbols = request.symbols or universe_members(db, request.universe)
    if not symbols:
        raise DataUnavailableError(f"Universe '{request.universe}' has no members.")

    weights = {k: float(v) for k, v in request.weights.items() if v}
    registry = all_factors()
    unknown = sorted(set(weights) - set(registry))
    if unknown:
        raise DataUnavailableError(f"Unknown factor(s): {', '.join(unknown)}")
    if not weights:
        raise DataUnavailableError("Provide at least one factor weight.")

    needed = sorted(set(weights) | {f.factor for f in request.filters})
    frame = _factor_frame(db, as_of, symbols, needed)
    if frame.empty:
        raise DataUnavailableError(f"No factor values stored for {as_of}.")

    basis = frame.pivot_table(index="symbol", columns="factor", values=request.basis)
    raws = frame.pivot_table(index="symbol", columns="factor", values="raw")
    deciles = frame.pivot_table(index="symbol", columns="factor", values="decile")

    total_weight = sum(abs(w) for w in weights.values()) or 1.0
    contributions = pd.DataFrame(index=basis.index)
    for name, weight in weights.items():
        column = basis[name] if name in basis.columns else pd.Series(0.0, index=basis.index)
        # A name missing one factor scores neutrally on it rather than being
        # dropped, which would bias the screen toward larger, better-covered
        # companies.
        contributions[name] = column.fillna(0.0) * (weight / total_weight)

    composite = contributions.sum(axis=1)

    passed = pd.Series(True, index=basis.index)
    for f in request.filters:
        column = raws[f.factor] if f.factor in raws.columns else pd.Series(dtype=float)
        column = column.reindex(basis.index)
        passed &= column.map(lambda v, flt=f: flt.passes(v))

    meta = _instrument_meta(db, list(basis.index))
    ranked = (
        pd.DataFrame(
            {
                "symbol": basis.index,
                "composite": composite.to_numpy(),
                "passed": passed.to_numpy(),
            }
        )
        .sort_values("composite", ascending=False)
        .reset_index(drop=True)
    )
    eligible = ranked[ranked["passed"]]

    selected: list[str] = []
    per_sector: dict[str, int] = {}
    for symbol in eligible["symbol"]:
        sector = meta.get(symbol, {}).get("sector") or "Unknown"
        if (
            request.max_per_sector is not None
            and per_sector.get(sector, 0) >= request.max_per_sector
        ):
            continue
        selected.append(symbol)
        per_sector[sector] = per_sector.get(sector, 0) + 1
        if len(selected) >= request.limit:
            break

    coverage = _coverage(db, as_of, list(weights))

    results = []
    for rank, symbol in enumerate(selected, start=1):
        info = meta.get(symbol, {})
        results.append(
            {
                "rank": rank,
                "symbol": symbol,
                "name": info.get("name"),
                "sector": info.get("sector"),
                "composite": round(float(composite.get(symbol, 0.0)), 4),
                "contributions": {
                    name: round(float(contributions.loc[symbol, name]), 4)
                    for name in weights
                    if symbol in contributions.index
                },
                "factors": {
                    name: {
                        "raw": _num(raws.loc[symbol, name]) if name in raws.columns else None,
                        "decile": (
                            _int(deciles.loc[symbol, name]) if name in deciles.columns else None
                        ),
                    }
                    for name in weights
                },
            }
        )

    return {
        "as_of": as_of.isoformat(),
        "universe": request.universe,
        "universe_size": len(symbols),
        "eligible": int(eligible.shape[0]),
        "returned": len(results),
        "basis": request.basis,
        "weights": weights,
        "coverage": coverage,
        "results": results,
    }


def _instrument_meta(db: Session, symbols: list[str]) -> dict[str, dict[str, Any]]:
    rows = db.execute(
        select(Instrument.symbol, Instrument.name, Instrument.sector).where(
            Instrument.symbol.in_(symbols)
        )
    ).all()
    return {s: {"name": n, "sector": sec} for s, n, sec in rows}


def _coverage(db: Session, as_of: dt.date, factors: list[str]) -> dict[str, float]:
    rows = db.execute(
        select(FactorCoverage.factor, FactorCoverage.coverage_pct).where(
            FactorCoverage.as_of == as_of, FactorCoverage.factor.in_(factors)
        )
    ).all()
    return {f: float(pct) for f, pct in rows}


def _num(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 4)


def _int(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)
