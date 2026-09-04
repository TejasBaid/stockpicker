"""Indian Stock API client (https://stock.indianapi.in).

The fundamentals source. Every endpoint keys off the plain NSE trading symbol
(``TATASTEEL``); the vendor's internal ``tickerId`` (``S0003026``) returns HTTP
500 and must not be used.

The vendor publishes no rate-limit or quota headers, so every call is counted
against a configured daily budget in ``provider_calls_daily`` and paced by a
token bucket. Responses are returned raw; normalisation lives in ``app.ingest``
so the untouched payload can be stored and remapped later without refetching.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ProviderError
from app.providers.base import CallBudget, RateLimiter, retry_call

log = structlog.get_logger(__name__)

PROVIDER = "indian_api"

# Empirically determined -- the vendor rejects anything else with a message
# listing the accepted values.
STATEMENT_TYPES = frozenset(
    {"cashflow", "yoy_results", "ttm_results", "quarter_results", "balancesheet"}
)
HISTORICAL_STATS_TYPES = frozenset(
    {
        "cashflow",
        "yoy_results",
        "quarter_results",
        "balancesheet",
        "ratios",
        "shareholding_pattern_quarterly",
        "shareholding_pattern_yearly",
        "profit_loss_stats",
        "all",
    }
)
VALUATION_FILTERS = ("pe", "ptb", "evebitda", "mcs")
FORECAST_MEASURES = ("EPS", "SAL", "ROE", "NET", "DPS", "EBI", "CPS")


class SymbolNotCovered(ProviderError):
    """The vendor has no data for this symbol. Permanent -- do not retry."""

    status_code = 404


class IndianApiClient:
    def __init__(self, db: Session, *, timeout: float = 30.0) -> None:
        settings = get_settings()
        if not settings.indian_api_key:
            raise ProviderError("INDIAN_API_KEY is not configured.")
        self._db = db
        self._budget = CallBudget(db, PROVIDER, settings.indian_api_daily_budget)
        self._limiter = RateLimiter(settings.indian_api_rate_per_sec)
        self._client = httpx.Client(
            base_url=settings.indian_api_base,
            headers={"x-api-key": settings.indian_api_key, "Accept": "application/json"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> IndianApiClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def budget(self) -> CallBudget:
        return self._budget

    # ---- core -------------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self._budget.check()
        self._limiter.acquire()

        def _do() -> Any:
            resp = self._client.get(path, params=params)
            if resp.status_code == 429:
                raise ProviderError("Rate limited by the Indian Stock API.")
            resp.raise_for_status()
            return resp.json()

        try:
            payload = retry_call(
                _do,
                label=f"indian_api{path}",
                give_up_on=(SymbolNotCovered,),
            )
        except Exception:
            self._budget.record(path, errored=True)
            raise

        self._budget.record(path)

        # The vendor signals failures with HTTP 200 and an error body, in two
        # different shapes: {"error": ...} and [{"error": ...}, 500].
        err = _extract_error(payload)
        if err is not None:
            raise SymbolNotCovered(f"{path}: {err}")
        return payload

    # ---- endpoints --------------------------------------------------------

    def stock(self, symbol: str, lookup_name: str | None = None) -> dict[str, Any]:
        """The big one: ~145 metrics, 8 annual + 11 interim statement periods,
        shareholding, peers and analyst ratings with 3 months of history.

        ``lookup_name`` overrides the symbol for the handful of companies the
        vendor cannot resolve by NSE code (those containing "&").
        """
        data = self._get("/stock", {"name": lookup_name or symbol})
        if not isinstance(data, dict) or "companyName" not in data:
            raise SymbolNotCovered(f"/stock returned no company for {symbol}")
        # The vendor sometimes returns a company shell with no metrics and no
        # financials at all. Writing that would create an all-null snapshot and
        # inflate the coverage figures, so treat it as no data.
        if not data.get("keyMetrics") and not data.get("financials"):
            raise SymbolNotCovered(f"/stock returned an empty payload for {symbol}")
        return data

    def statement(self, symbol: str, stats: str) -> Any:
        if stats not in STATEMENT_TYPES:
            raise ValueError(f"Unsupported statement type {stats!r}")
        return self._get("/statement", {"stock_name": symbol, "stats": stats})

    def historical_stats(self, symbol: str, stats: str) -> Any:
        if stats not in HISTORICAL_STATS_TYPES:
            raise ValueError(f"Unsupported historical stats type {stats!r}")
        return self._get("/historical_stats", {"stock_name": symbol, "stats": stats})

    def historical_data(self, symbol: str, period: str = "5yr", filter_: str = "price") -> Any:
        """Weekly price series, or a valuation-multiple series when ``filter_``
        is one of pe / ptb / evebitda / mcs."""
        return self._get(
            "/historical_data", {"stock_name": symbol, "period": period, "filter": filter_}
        )

    def corporate_actions(self, symbol: str) -> Any:
        return self._get("/corporate_actions", {"stock_name": symbol})

    def recent_announcements(self, symbol: str) -> Any:
        return self._get("/recent_announcements", {"stock_name": symbol})

    def forecasts(
        self,
        symbol: str,
        measure: str = "EPS",
        *,
        period_type: str = "Annual",
        data_type: str = "Actuals",
        age: str = "Current",
    ) -> Any:
        """Analyst actuals and estimates.

        Carries ``ActualReportDate`` -- the real earnings announcement date --
        which is the primary source for point-in-time ``known_on`` elsewhere,
        plus ``SurprisePercent`` and ``StandardizedUnexpectedEarnings``.
        """
        return self._get(
            "/stock_forecasts",
            {
                "stock_id": symbol,
                "measure_code": measure,
                "period_type": period_type,
                "data_type": data_type,
                "age": age,
            },
        )

    def target_price(self, symbol: str) -> Any:
        return self._get("/stock_target_price", {"stock_id": symbol})

    def industry_search(self, query: str) -> Any:
        return self._get("/industry_search", {"query": query})

    def trending(self) -> Any:
        return self._get("/trending", None)

    def price_shockers(self) -> Any:
        return self._get("/price_shockers", None)

    def week_52_high_low(self) -> Any:
        return self._get("/fetch_52_week_high_low_data", None)


def _extract_error(payload: Any) -> str | None:
    """The vendor returns errors with a 200 status in a couple of shapes."""
    if isinstance(payload, dict) and "error" in payload:
        return str(payload["error"])
    if (
        isinstance(payload, list)
        and payload
        and isinstance(payload[0], dict)
        and "error" in payload[0]
    ):
        return str(payload[0]["error"])
    return None
