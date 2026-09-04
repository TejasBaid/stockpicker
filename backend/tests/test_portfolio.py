"""Portfolio tracking: P&L, FIFO tax treatment, exit triggers, factor decay."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.market import DailyBar, Instrument
from app.db.models.portfolio import Portfolio, Position, Trade
from app.services import portfolio as service
from app.services.auth import create_invite, redeem_invite

SYMBOL = "ZZPORT"


@pytest.fixture
def user(db: Session) -> User:
    return redeem_invite(
        db,
        code=create_invite(db),
        email=f"pf-{uuid.uuid4().hex[:8]}@example.com",
        display_name="PF",
        password="correct-horse-9-battery",
    )


@pytest.fixture
def portfolio(db: Session, user: User) -> Portfolio:
    db.add(Instrument(symbol=SYMBOL, name="Test Co", sector="Tech", exchange="NSE"))
    db.flush()  # bars reference the instrument, so it must exist first
    # A price series with real intraday range, so ATR is meaningful.
    base = dt.date(2025, 1, 1)
    for i in range(30):
        price = 100.0 + i
        db.add(
            DailyBar(
                symbol=SYMBOL,
                date=base + dt.timedelta(days=i),
                open=price,
                high=price + 3,
                low=price - 2,
                close=price,
                volume=100000,
            )
        )
    p = Portfolio(owner_id=user.id, name="Test", cash=Decimal("50000"))
    db.add(p)
    db.commit()
    return p


def _add_position(db: Session, p: Portfolio, qty: str, price: str, opened: dt.date) -> Position:
    pos = Position(
        portfolio_id=p.id,
        symbol=SYMBOL,
        quantity=Decimal(qty),
        avg_price=Decimal(price),
        opened_on=opened,
    )
    db.add(pos)
    db.flush()
    db.add(
        Trade(
            position_id=pos.id,
            side="BUY",
            quantity=Decimal(qty),
            price=Decimal(price),
            traded_on=opened,
        )
    )
    db.commit()
    db.refresh(p)
    return pos


def test_pnl_uses_the_latest_close(db: Session, portfolio: Portfolio) -> None:
    _add_position(db, portfolio, "100", "100", dt.date(2025, 1, 1))
    summary = service.summarise(db, portfolio)
    # Last close in the fixture is 129.
    assert summary["invested"] == pytest.approx(10_000)
    assert summary["market_value"] == pytest.approx(12_900)
    assert summary["pnl"] == pytest.approx(2_900)
    assert summary["pnl_pct"] == pytest.approx(29.0)
    assert summary["total_value"] == pytest.approx(12_900 + 50_000)


def test_holding_period_drives_tax_status(db: Session, portfolio: Portfolio) -> None:
    _add_position(db, portfolio, "10", "100", dt.date.today() - dt.timedelta(days=400))
    long_held = service.position_detail(db, portfolio)[0]
    assert long_held["tax_status"] == "long-term"
    assert long_held["days_to_long_term"] == 0


def test_short_holdings_report_days_remaining(db: Session, portfolio: Portfolio) -> None:
    _add_position(db, portfolio, "10", "100", dt.date.today() - dt.timedelta(days=100))
    held = service.position_detail(db, portfolio)[0]
    assert held["tax_status"] == "short-term"
    assert held["days_to_long_term"] == pytest.approx(265, abs=1)


def test_realised_gains_match_lots_first_in_first_out(db: Session, portfolio: Portfolio) -> None:
    """Two lots at different prices, one partial sale: the older lot must be
    consumed first, which is what Indian brokers report."""
    pos = _add_position(db, portfolio, "100", "100", dt.date(2023, 1, 1))
    db.add(
        Trade(
            position_id=pos.id,
            side="BUY",
            quantity=Decimal("100"),
            price=Decimal("200"),
            traded_on=dt.date(2024, 6, 1),
        )
    )
    db.add(
        Trade(
            position_id=pos.id,
            side="SELL",
            quantity=Decimal("100"),
            price=Decimal("300"),
            traded_on=dt.date(2024, 7, 1),
        )
    )
    db.commit()

    tax = service.realised_gains(db, portfolio)
    # The 2023 lot (cost 100) is sold at 300, held >1 year -> long-term 20,000.
    assert tax["long_term_gain"] == pytest.approx(20_000)
    assert tax["short_term_gain"] == pytest.approx(0)


def test_short_term_sale_is_taxed_at_the_higher_rate(db: Session, portfolio: Portfolio) -> None:
    pos = _add_position(db, portfolio, "100", "100", dt.date(2025, 1, 1))
    db.add(
        Trade(
            position_id=pos.id,
            side="SELL",
            quantity=Decimal("100"),
            price=Decimal("150"),
            traded_on=dt.date(2025, 3, 1),
        )
    )
    db.commit()
    tax = service.realised_gains(db, portfolio)
    assert tax["short_term_gain"] == pytest.approx(5_000)
    assert tax["estimated_tax"] == pytest.approx(5_000 * 0.20)


def test_long_term_exemption_is_applied(db: Session, portfolio: Portfolio) -> None:
    pos = _add_position(db, portfolio, "1000", "100", dt.date(2023, 1, 1))
    db.add(
        Trade(
            position_id=pos.id,
            side="SELL",
            quantity=Decimal("1000"),
            price=Decimal("200"),
            traded_on=dt.date(2024, 6, 1),
        )
    )
    db.commit()
    tax = service.realised_gains(db, portfolio)
    assert tax["long_term_gain"] == pytest.approx(100_000)
    # Below the 1.25 lakh exemption, so no tax.
    assert tax["estimated_tax"] == pytest.approx(0)


def test_atr_stop_suggestion_sits_below_the_price(db: Session, portfolio: Portfolio) -> None:
    suggestion = service.suggest_stop(db, SYMBOL, multiple=2.5)
    assert suggestion["atr"] is not None
    assert suggestion["stop"] < suggestion["price"]
    assert suggestion["stop_distance_pct"] < 0


def test_exit_plan_triggers_when_the_stop_is_breached(db: Session, portfolio: Portfolio) -> None:
    pos = _add_position(db, portfolio, "100", "100", dt.date(2025, 1, 1))
    # Last close is 129; a stop at 140 is already breached.
    service.create_exit_plan(db, pos, stop_type="percent", stop_price=140.0)
    db.refresh(pos)
    detail = service.position_detail(db, portfolio)[0]
    assert detail["exit_plan"]["triggers"]
    assert "stop" in detail["exit_plan"]["triggers"][0].lower()


def test_untriggered_stop_reports_no_alert(db: Session, portfolio: Portfolio) -> None:
    pos = _add_position(db, portfolio, "100", "100", dt.date(2025, 1, 1))
    service.create_exit_plan(db, pos, stop_type="percent", stop_price=90.0)
    db.refresh(pos)
    detail = service.position_detail(db, portfolio)[0]
    assert detail["exit_plan"]["triggers"] == []


def test_target_ladder_triggers_a_trim(db: Session, portfolio: Portfolio) -> None:
    pos = _add_position(db, portfolio, "100", "100", dt.date(2025, 1, 1))
    service.create_exit_plan(
        db, pos, target_ladder=[{"price": 120, "pct": 33}, {"price": 500, "pct": 50}]
    )
    db.refresh(pos)
    triggers = service.position_detail(db, portfolio)[0]["exit_plan"]["triggers"]
    assert len(triggers) == 1  # 120 reached, 500 not
    assert "120" in triggers[0]


def test_factor_drift_reports_deterioration(db: Session, portfolio: Portfolio) -> None:
    from app.db.models.factors import FactorValue

    as_of = dt.date.today()
    db.add(
        FactorValue(
            symbol=SYMBOL,
            as_of=as_of,
            factor="roe",
            raw=10.0,
            zscore=0.0,
            sector_zscore=0.0,
            percentile=50.0,
            decile=8,
        )
    )
    pos = _add_position(db, portfolio, "10", "100", dt.date(2025, 1, 1))
    pos.entry_factors = {"roe": 2}
    db.commit()

    drift = service.position_detail(db, portfolio)[0]["factor_drift"]
    assert drift[0]["factor"] == "roe"
    assert drift[0]["entry_decile"] == 2
    assert drift[0]["current_decile"] == 8
    assert drift[0]["drift"] == 6  # deciles run 1 best -> 10 worst


def test_rebalance_proposal_moves_toward_targets(db: Session, portfolio: Portfolio) -> None:
    _add_position(db, portfolio, "100", "100", dt.date(2025, 1, 1))
    proposals = service.rebalance_proposal(db, portfolio, {SYMBOL: 0.10})
    assert proposals
    # Currently ~20% of a 62,900 portfolio, target 10% -> must sell.
    assert proposals[0]["side"] == "SELL"
    assert proposals[0]["symbol"] == SYMBOL
