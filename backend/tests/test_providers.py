"""Provider plumbing: rate limiting, budget enforcement, retry semantics, and
the standing guarantee that the Groww client cannot touch the account."""

from __future__ import annotations

import inspect
import time

import pytest
from sqlalchemy.orm import Session

from app.core.errors import BudgetExceededError
from app.providers import groww as groww_module
from app.providers.base import CallBudget, RateLimiter, retry_call


def test_rate_limiter_paces_calls() -> None:
    limiter = RateLimiter(rate_per_sec=20, burst=1)
    start = time.monotonic()
    for _ in range(5):
        limiter.acquire()
    elapsed = time.monotonic() - start
    # 5 tokens at 20/s with a burst of 1 needs at least ~4 refill intervals.
    assert elapsed >= 0.15


def test_budget_blocks_once_exhausted(db: Session) -> None:
    budget = CallBudget(db, "test_provider", daily_limit=3)
    for _ in range(3):
        budget.check()
        budget.record("/thing")
    assert budget.used_today() == 3
    assert budget.remaining() == 0
    with pytest.raises(BudgetExceededError, match="exhausted"):
        budget.check()


def test_cached_calls_do_not_consume_budget(db: Session) -> None:
    budget = CallBudget(db, "test_cached", daily_limit=2)
    budget.record("/thing", cached=True)
    budget.record("/thing", cached=True)
    assert budget.used_today() == 0
    budget.check()


def test_unlimited_budget_never_blocks(db: Session) -> None:
    budget = CallBudget(db, "test_unlimited", daily_limit=None)
    assert budget.remaining() is None
    budget.check(cost=10_000)


def test_retry_gives_up_immediately_on_permanent_errors() -> None:
    """Retrying a symbol the vendor does not have wastes time and quota."""

    class Permanent(Exception):
        pass

    calls = 0

    def fn() -> None:
        nonlocal calls
        calls += 1
        raise Permanent("no such symbol")

    with pytest.raises(Permanent):
        retry_call(fn, attempts=3, base_delay=0.01, give_up_on=(Permanent,))
    assert calls == 1


def test_retry_retries_transient_errors_then_succeeds() -> None:
    calls = 0

    def fn() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TimeoutError("flaky")
        return "ok"

    assert retry_call(fn, attempts=3, base_delay=0.01) == "ok"
    assert calls == 3


ACCOUNT_METHOD_MARKERS = (
    "holding",
    "position",
    "order",
    "margin",
    "trade",
    "portfolio",
    "profile",
)


def test_groww_client_exposes_no_account_methods() -> None:
    """A product guarantee, enforced as a test: this platform never reads or
    touches the brokerage account. Only market data is permitted.

    ``daily_candles`` is exempt from the "trade" marker because the underlying
    vendor argument is called trading_symbol.
    """
    public = [
        name
        for name, _ in inspect.getmembers(groww_module.GrowwClient, callable)
        if not name.startswith("_")
    ]
    offenders = [
        name for name in public if any(marker in name.lower() for marker in ACCOUNT_METHOD_MARKERS)
    ]
    assert offenders == [], f"Groww client must stay market-data only, found: {offenders}"


def test_groww_module_never_references_account_endpoints() -> None:
    """Guards against someone adding an account call inside an existing method."""
    import pathlib

    source = pathlib.Path(groww_module.__file__).read_text()
    banned = (
        "get_holdings_for_user",
        "get_positions_for_user",
        "place_order",
        "modify_order",
        "cancel_order",
        "get_available_margin_details",
        "get_order_list",
    )
    found = [b for b in banned if b in source]
    assert found == [], f"Account endpoints must never be called: {found}"
