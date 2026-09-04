"""Screener behaviour: weighting, gating, sector caps and the point-in-time
guarantee that makes a backtest trustworthy."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DataUnavailableError
from app.db.models.factors import FactorValue
from app.db.models.market import Instrument, Universe, UniverseMember
from app.factors.registry import all_factors
from app.screener.service import Filter, ScreenRequest, run_screen
from app.strategy.presets import PRESETS

AS_OF = dt.date(2020, 1, 15)  # far enough back not to collide with real data
UNIVERSE = "pytest_universe"


@pytest.fixture
def seeded(db: Session) -> list[str]:
    """A tiny synthetic universe with known factor values."""
    symbols = ["ZZA", "ZZB", "ZZC", "ZZD"]
    sectors = {"ZZA": "Tech", "ZZB": "Tech", "ZZC": "Energy", "ZZD": "Energy"}
    for s in symbols:
        db.add(Instrument(symbol=s, name=f"Test {s}", sector=sectors[s], exchange="NSE"))
    universe = Universe(slug=UNIVERSE, name="Test", is_system=False)
    db.add(universe)
    db.flush()
    for s in symbols:
        db.add(UniverseMember(universe_id=universe.id, symbol=s))

    # roe: A best .. D worst. liquidity: C is illiquid.
    roe = {"ZZA": 40.0, "ZZB": 30.0, "ZZC": 20.0, "ZZD": 10.0}
    liq = {"ZZA": 100.0, "ZZB": 80.0, "ZZC": 1.0, "ZZD": 50.0}
    for s in symbols:
        db.add(
            FactorValue(
                symbol=s,
                as_of=AS_OF,
                factor="roe",
                raw=roe[s],
                zscore=(roe[s] - 25) / 12.5,
                sector_zscore=(roe[s] - 25) / 12.5,
                percentile=roe[s],
                decile=1,
            )
        )
        db.add(
            FactorValue(
                symbol=s,
                as_of=AS_OF,
                factor="liquidity",
                raw=liq[s],
                zscore=0.0,
                sector_zscore=0.0,
                percentile=liq[s],
                decile=1,
            )
        )
    db.commit()
    return symbols


def test_ranks_by_weighted_score(db: Session, seeded: list[str]) -> None:
    out = run_screen(
        db, ScreenRequest(weights={"roe": 1.0}, universe=UNIVERSE, as_of=AS_OF, limit=10)
    )
    assert [r["symbol"] for r in out["results"]] == ["ZZA", "ZZB", "ZZC", "ZZD"]
    assert out["results"][0]["composite"] > out["results"][-1]["composite"]


def test_filters_gate_before_ranking(db: Session, seeded: list[str]) -> None:
    out = run_screen(
        db,
        ScreenRequest(
            weights={"roe": 1.0},
            universe=UNIVERSE,
            as_of=AS_OF,
            filters=[Filter("liquidity", "gte", 10.0)],
        ),
    )
    assert "ZZC" not in [r["symbol"] for r in out["results"]]
    assert out["eligible"] == 3


def test_missing_factor_data_fails_a_gate_rather_than_passing_it(
    db: Session, seeded: list[str]
) -> None:
    """A name with no value for a gated factor must not slip through: silence
    is not evidence of passing."""
    db.execute(
        select(FactorValue).where(FactorValue.symbol == "ZZA", FactorValue.factor == "liquidity")
    )
    row = db.scalar(
        select(FactorValue).where(FactorValue.symbol == "ZZA", FactorValue.factor == "liquidity")
    )
    assert row is not None
    db.delete(row)
    db.commit()

    out = run_screen(
        db,
        ScreenRequest(
            weights={"roe": 1.0},
            universe=UNIVERSE,
            as_of=AS_OF,
            filters=[Filter("liquidity", "gte", 10.0)],
        ),
    )
    assert "ZZA" not in [r["symbol"] for r in out["results"]]


def test_sector_cap_diversifies_the_result(db: Session, seeded: list[str]) -> None:
    out = run_screen(
        db,
        ScreenRequest(
            weights={"roe": 1.0}, universe=UNIVERSE, as_of=AS_OF, max_per_sector=1, limit=10
        ),
    )
    symbols = [r["symbol"] for r in out["results"]]
    assert symbols == ["ZZA", "ZZC"]  # best of each sector only


def test_limit_is_respected(db: Session, seeded: list[str]) -> None:
    out = run_screen(
        db, ScreenRequest(weights={"roe": 1.0}, universe=UNIVERSE, as_of=AS_OF, limit=2)
    )
    assert out["returned"] == 2


def test_unknown_factor_is_rejected(db: Session, seeded: list[str]) -> None:
    with pytest.raises(DataUnavailableError, match="Unknown factor"):
        run_screen(db, ScreenRequest(weights={"not_a_factor": 1.0}, universe=UNIVERSE, as_of=AS_OF))


def test_empty_weights_are_rejected(db: Session, seeded: list[str]) -> None:
    with pytest.raises(DataUnavailableError, match="at least one factor"):
        run_screen(db, ScreenRequest(weights={}, universe=UNIVERSE, as_of=AS_OF))


def test_a_date_with_no_factor_data_is_reported_clearly(db: Session, seeded: list[str]) -> None:
    with pytest.raises(DataUnavailableError, match="No factor values"):
        run_screen(
            db,
            ScreenRequest(weights={"roe": 1.0}, universe=UNIVERSE, as_of=dt.date(2019, 1, 1)),
        )


def test_every_preset_references_real_factors() -> None:
    """A preset naming a factor that no longer exists would fail only when a
    user happened to select it."""
    known = set(all_factors())
    for slug, preset in PRESETS.items():
        unknown_weights = set(preset["weights"]) - known
        unknown_filters = {f["factor"] for f in preset.get("filters", [])} - known
        assert not unknown_weights, f"{slug} weights unknown factors: {unknown_weights}"
        assert not unknown_filters, f"{slug} filters unknown factors: {unknown_filters}"
        assert abs(sum(preset["weights"].values()) - 1.0) < 0.01, f"{slug} weights must sum to 1"
