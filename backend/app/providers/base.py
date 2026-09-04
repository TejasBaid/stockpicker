"""Shared provider plumbing: rate limiting, call budgets and retries.

Neither vendor is generous or well documented about limits, so the client side
is deliberately conservative:

* Groww publishes 10 req/s and 300/min; we run below that.
* The Indian Stock API publishes no quota headers at all and its pricing page
  is JS-gated, so we enforce our own daily ceiling and count every call in
  ``provider_calls_daily``. Running out of quota mid-week is far worse than a
  slower ingest.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.errors import BudgetExceededError
from app.db.models.ops import ProviderCallDaily

log = structlog.get_logger(__name__)


class RateLimiter:
    """Token bucket. Thread-safe, blocking."""

    def __init__(self, rate_per_sec: float, burst: int | None = None) -> None:
        self.rate = rate_per_sec
        self.capacity = float(burst if burst is not None else max(1.0, rate_per_sec))
        self._tokens = self.capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                wait = deficit / self.rate
            time.sleep(wait)


class CallBudget:
    """Per-provider daily call accounting, persisted so it survives restarts and
    is shared between the web process and the ingest worker."""

    def __init__(self, db: Session, provider: str, daily_limit: int | None) -> None:
        self.db = db
        self.provider = provider
        self.daily_limit = daily_limit

    def _today(self) -> date:
        return datetime.now(UTC).date()

    def used_today(self) -> int:
        return int(
            self.db.scalar(
                select(func.coalesce(func.sum(ProviderCallDaily.count), 0)).where(
                    ProviderCallDaily.provider == self.provider,
                    ProviderCallDaily.call_date == self._today(),
                )
            )
            or 0
        )

    def remaining(self) -> int | None:
        if self.daily_limit is None:
            return None
        return max(0, self.daily_limit - self.used_today())

    def check(self, cost: int = 1) -> None:
        remaining = self.remaining()
        if remaining is not None and remaining < cost:
            raise BudgetExceededError(
                f"Daily {self.provider} call budget of {self.daily_limit} is exhausted. "
                "Raise INDIAN_API_DAILY_BUDGET or wait until tomorrow."
            )

    def record(self, endpoint: str, *, errored: bool = False, cached: bool = False) -> None:
        stmt = (
            pg_insert(ProviderCallDaily)
            .values(
                provider=self.provider,
                call_date=self._today(),
                endpoint=endpoint,
                count=0 if cached else 1,
                error_count=1 if errored else 0,
                cached_count=1 if cached else 0,
            )
            .on_conflict_do_update(
                index_elements=["provider", "call_date", "endpoint"],
                set_={
                    "count": ProviderCallDaily.count + (0 if cached else 1),
                    "error_count": ProviderCallDaily.error_count + (1 if errored else 0),
                    "cached_count": ProviderCallDaily.cached_count + (1 if cached else 0),
                },
            )
        )
        self.db.execute(stmt)
        self.db.commit()


def retry_call[T](
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 1.5,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    give_up_on: tuple[type[BaseException], ...] = (),
    label: str = "call",
) -> T:
    """Retry with exponential backoff.

    ``give_up_on`` is checked first so that permanent failures (a symbol the
    vendor does not cover, an auth error) fail fast instead of burning quota on
    three identical requests.
    """
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except give_up_on:
            raise
        except retry_on as exc:
            last = exc
            if attempt == attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            log.warning("provider.retry", label=label, attempt=attempt, delay=delay, error=str(exc))
            time.sleep(delay)
    assert last is not None
    raise last


__all__ = ["CallBudget", "RateLimiter", "retry_call"]
