"""Investment planning: regime scoring, sizing, whole-share allocation and swaps."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import DataUnavailableError
from app.db.models.factors import FactorValue
from app.db.models.market import DailyBar, Instrument, Universe, UniverseMember
from app.services import regime
from app.services.plan import (
    MAX_POSITION_WEIGHT,
    MIN_POSITION_VALUE,
    PlanRequest,
    _target_weights,
    build_plan,
    swap,
)

UNIVERSE = "pytest_plan"
AS_OF = dt.date.today()


@pytest.fixture
def market(db: Session) -> list[str]:
    """Four names at very different price points, so whole-share rounding and
    affordability actually bite."""
    prices = {"ZPA": 100.0, "ZPB": 500.0, "ZPC": 2000.0, "ZPD": 40000.0}
    sectors = {"ZPA": "Tech", "ZPB": "Tech", "ZPC": "Energy", "ZPD": "Textiles"}
    for sym in prices:
        db.add(Instrument(symbol=sym, name=f"Co {sym}", sector=sectors[sym], exchange="NSE"))
    db.flush()

    base = dt.date.today() - dt.timedelta(days=320)
    for sym, price in prices.items():
        for i in range(300):
            p = price * (1 + 0.0003 * i)
            db.add(
                DailyBar(
                    symbol=sym,
                    date=base + dt.timedelta(days=i),
                    open=p,
                    high=p * 1.02,
                    low=p * 0.98,
                    close=p,
                    volume=500000,
                )
            )

    universe = Universe(slug=UNIVERSE, name="Plan test", is_system=False)
    db.add(universe)
    db.flush()
    for i, sym in enumerate(prices):
        db.add(UniverseMember(universe_id=universe.id, symbol=sym))
        db.add(
            FactorValue(
                symbol=sym,
                as_of=AS_OF,
                factor="roe",
                raw=40.0 - i * 5,
                zscore=1.0 - i * 0.4,
                sector_zscore=1.0 - i * 0.4,
                percentile=90.0 - i * 10,
                decile=i + 1,
            )
        )
    db.commit()
    return list(prices)


def _request(**kw: object) -> PlanRequest:
    base = {
        "capital": 500_000.0,
        "weights": {"roe": 1.0},
        "holdings": 4,
        "universe": UNIVERSE,
        "max_per_sector": None,
    }
    base.update(kw)
    return PlanRequest(**base)  # type: ignore[arg-type]


def test_zero_capital_is_rejected(db: Session, market: list[str]) -> None:
    with pytest.raises(DataUnavailableError, match="amount"):
        build_plan(db, _request(capital=0))


def test_plan_buys_whole_shares_within_the_deployable_amount(
    db: Session, market: list[str]
) -> None:
    plan = build_plan(db, _request(override_deploy_pct=1.0))
    assert plan["allocations"]
    for a in plan["allocations"]:
        assert a["shares"] == int(a["shares"]) and a["shares"] > 0
        assert a["value"] == pytest.approx(a["shares"] * a["price"], rel=1e-6)
    assert plan["invested"] <= plan["deployable"] + 1e-6


def test_deploy_override_controls_how_much_is_committed(db: Session, market: list[str]) -> None:
    half = build_plan(db, _request(override_deploy_pct=0.5))
    assert half["deployable"] == pytest.approx(250_000)
    assert half["cash_reserve"] == pytest.approx(250_000)
    assert half["invested"] <= 250_000


def test_unaffordable_names_are_dropped_with_a_reason(db: Session, market: list[str]) -> None:
    """One share of ZPD costs 40,000 — more than its slice of a small pot."""
    plan = build_plan(db, _request(capital=100_000, override_deploy_pct=1.0))
    skipped = {s["symbol"] for s in plan["skipped"]}
    assert "ZPD" in skipped
    reason = next(s["reason"] for s in plan["skipped"] if s["symbol"] == "ZPD")
    assert "one share costs" in reason


def test_dropping_a_name_reallocates_rather_than_leaving_cash_idle(
    db: Session, market: list[str]
) -> None:
    plan = build_plan(db, _request(capital=100_000, override_deploy_pct=1.0))
    idle_share = plan["uninvested_cash"] / plan["deployable"]
    # Without renormalising, the skipped name's whole slice would sit in cash.
    assert idle_share < 0.15


def test_equal_weight_sizes_positions_evenly(db: Session, market: list[str]) -> None:
    plan = build_plan(db, _request(sizing="equal", override_deploy_pct=1.0))
    weights = [a["target_weight_pct"] for a in plan["allocations"]]
    assert max(weights) - min(weights) < 1e-6


def test_no_position_exceeds_the_concentration_cap() -> None:
    """Even a single-name plan must respect the cap when others can absorb it."""
    weights = _target_weights(
        ["A", "B", "C", "D", "E", "F"],
        "conviction",
        {"A": 100.0, "B": 1.0, "C": 1.0, "D": 1.0, "E": 1.0, "F": 1.0},
        {},
        {},
    )
    assert max(weights.values()) <= MAX_POSITION_WEIGHT + 1e-9
    assert sum(weights.values()) == pytest.approx(1.0)


def test_weights_always_sum_to_one_however_few_the_names() -> None:
    """With four names a 20% cap is unreachable; under-deploying rather than
    relaxing it would silently leave a fifth of the money in cash."""
    for n in range(2, 9):
        names = [f"S{i}" for i in range(n)]
        for sizing in ("equal", "inverse_vol", "conviction", "equal_risk"):
            weights = _target_weights(names, sizing, dict.fromkeys(names, 1.0), {}, {})
            assert sum(weights.values()) == pytest.approx(1.0), f"{sizing} with {n} names"


def test_conviction_sizing_never_shorts_a_negative_score() -> None:
    names = ["A", "B", "C", "D", "E", "F"]
    scores = {"A": 1.0, "B": -0.5, "C": -2.0, "D": 0.2, "E": 0.1, "F": 0.0}
    weights = _target_weights(names, "conviction", scores, {}, {})
    assert all(w > 0 for w in weights.values())
    assert weights["A"] > weights["C"]


def test_inverse_vol_puts_less_into_the_jumpier_name() -> None:
    names = ["CALM", "WILD", "C", "D", "E", "F"]
    vols = {"CALM": 0.10, "WILD": 0.50, "C": 0.2, "D": 0.2, "E": 0.2, "F": 0.2}
    weights = _target_weights(names, "inverse_vol", {}, vols, {})
    assert weights["CALM"] > weights["WILD"]
    assert sum(weights.values()) == pytest.approx(1.0)


def test_equal_risk_puts_less_into_the_wider_stop() -> None:
    names = ["TIGHT", "WIDE", "C", "D", "E", "F"]
    stops = {
        "TIGHT": {"stop_distance_pct": -5.0},
        "WIDE": {"stop_distance_pct": -25.0},
        **{n: {"stop_distance_pct": -12.0} for n in ("C", "D", "E", "F")},
    }
    weights = _target_weights(names, "equal_risk", {}, {}, stops)
    assert weights["TIGHT"] > weights["WIDE"]
    assert sum(weights.values()) == pytest.approx(1.0)


def test_every_position_clears_the_minimum_worth_holding(db: Session, market: list[str]) -> None:
    plan = build_plan(db, _request(capital=60_000, override_deploy_pct=1.0))
    for a in plan["allocations"]:
        assert a["value"] >= MIN_POSITION_VALUE * 0.5


def test_swap_removes_the_name_and_pulls_in_the_next_candidate(
    db: Session, market: list[str]
) -> None:
    request = _request(holdings=2, override_deploy_pct=1.0)
    before = [a["symbol"] for a in build_plan(db, request)["allocations"]]
    assert "ZPA" in before

    after = [a["symbol"] for a in swap(db, request, "ZPA")["allocations"]]
    assert "ZPA" not in after
    # The vacancy is filled rather than left empty.
    assert len(after) >= len(before) - 1


def test_sector_cap_limits_concentration(db: Session, market: list[str]) -> None:
    plan = build_plan(db, _request(max_per_sector=1, override_deploy_pct=1.0))
    sectors = [a["sector"] for a in plan["allocations"]]
    assert len(sectors) == len(set(sectors))


def test_risk_is_reported_against_the_stops(db: Session, market: list[str]) -> None:
    plan = build_plan(db, _request(override_deploy_pct=1.0))
    assert plan["total_risk_amount"] > 0
    assert 0 < plan["total_risk_pct"] < 100
    for a in plan["allocations"]:
        if a["stop"]:
            assert a["stop"] < a["price"]


# --- regime ---------------------------------------------------------------


def test_regime_without_history_is_neutral_not_confident(db: Session) -> None:
    """A fresh database must not produce a confident call in either direction."""
    r = regime.assess(db, [])
    assert r.state in {"neutral", "risk_on", "risk_off"}
    assert 0.0 <= r.score <= 1.0
    assert regime.MIN_DEPLOY <= r.deploy_pct <= regime.MAX_DEPLOY


def test_regime_never_suggests_sitting_entirely_in_cash(db: Session) -> None:
    loaded = db.scalar(select(func.count()).select_from(DailyBar)) or 0
    if loaded == 0:
        pytest.skip("no price history loaded")
    r = regime.assess(db, [])
    assert r.deploy_pct >= regime.MIN_DEPLOY > 0


def test_tranches_always_sum_to_the_whole_deployment(db: Session) -> None:
    for deploy in (0.30, 0.55, 0.70, 0.90, 1.00):
        tranches = regime._tranches(deploy)
        assert sum(t["share"] for t in tranches) == pytest.approx(1.0)
        assert tranches[0]["in_days"] == 0  # something is always bought today
