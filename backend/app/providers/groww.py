"""Groww market-data client.

**This client is market data only.** It deliberately exposes no method that
touches the brokerage account -- no holdings, positions, orders, margin or
trades. That is a product requirement, enforced here by omission and by
``test_groww_client_exposes_no_account_methods``.

Two quirks of the vendor API shape this module:

1. The current ``get_historical_candles`` endpoint returns ``open`` as null for
   every daily equity candle, and caps a request at 180 days. The deprecated
   ``get_historical_candle_data`` returns complete OHLCV *and* allows 1080 days
   per request. So daily bars use the deprecated endpoint and fall back to the
   current one (accepting a null open) only if it disappears.
2. Access tokens expire daily at 06:00 IST, so the token is cached in-process
   and regenerated on expiry.
"""

from __future__ import annotations

import datetime as dt
import threading
import warnings
from dataclasses import dataclass
from typing import Any

import pandas as pd
import structlog

from app.core.config import get_settings
from app.core.errors import ProviderError
from app.providers.base import RateLimiter, retry_call

log = structlog.get_logger(__name__)

# The deprecated daily endpoint allows 1080 days; stay just inside it.
MAX_DAILY_RANGE_DAYS = 1000
NIFTY_SYMBOL = "NIFTY"

# Vendor messages that mean "this will never work" -- retrying wastes time and
# quota on symbols that simply do not exist at Groww.
PERMANENT_ERROR_MARKERS = (
    "correct value of trading symbol",
    "invalid trading symbol",
    "symbol not found",
)


class UnknownSymbol(ProviderError):
    """Groww does not list this trading symbol. Permanent."""

    status_code = 404


@dataclass(frozen=True)
class Candle:
    date: dt.date
    open: float | None
    high: float
    low: float
    close: float
    volume: float


class GrowwClient:
    def __init__(self, rate_per_sec: float | None = None) -> None:
        settings = get_settings()
        self._api_key = settings.groww_api_key
        self._secret = settings.groww_secret
        self._limiter = RateLimiter(rate_per_sec or settings.groww_rate_per_sec)
        self._client: Any = None
        self._token_expires_at: dt.datetime | None = None
        self._lock = threading.Lock()

    # ---- auth -------------------------------------------------------------

    def _decode_expiry(self, token: str) -> dt.datetime | None:
        import base64
        import json

        try:
            payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
            return dt.datetime.fromtimestamp(payload["exp"], dt.UTC)
        except Exception:
            return None

    @property
    def api(self) -> Any:
        """The underlying SDK client, refreshing the daily token when needed."""
        from growwapi import GrowwAPI

        with self._lock:
            expired = self._token_expires_at is not None and dt.datetime.now(
                dt.UTC
            ) >= self._token_expires_at - dt.timedelta(minutes=5)
            if self._client is None or expired:
                if not self._api_key or not self._secret:
                    raise ProviderError("Groww credentials are not configured.")
                token = retry_call(
                    lambda: GrowwAPI.get_access_token(api_key=self._api_key, secret=self._secret),
                    label="groww.token",
                )
                self._token_expires_at = self._decode_expiry(token)
                self._client = GrowwAPI(token)
                log.info("groww.authenticated", expires_at=self._token_expires_at)
            return self._client

    # ---- instruments ------------------------------------------------------

    def equity_instruments(self) -> pd.DataFrame:
        """NSE cash-segment equities only.

        The master list carries ~134k rows including bonds, debentures and
        derivatives; filtering on ``series == 'EQ'`` leaves ~2,600 real equities.
        """
        self._limiter.acquire()
        df = retry_call(lambda: self.api.get_all_instruments(), label="groww.instruments")
        return df[
            (df.exchange == "NSE")
            & (df.segment == "CASH")
            & (df.instrument_type == "EQ")
            & (df.series == "EQ")
        ].copy()

    # ---- historical bars --------------------------------------------------

    def daily_candles(self, symbol: str, start: dt.date, end: dt.date) -> list[Candle]:
        """Daily OHLCV, paginated across the vendor's per-request range cap."""
        out: list[Candle] = []
        cursor = start
        while cursor <= end:
            window_end = min(end, cursor + dt.timedelta(days=MAX_DAILY_RANGE_DAYS))
            out.extend(self._daily_window(symbol, cursor, window_end))
            cursor = window_end + dt.timedelta(days=1)

        seen: dict[dt.date, Candle] = {c.date: c for c in out}
        return [seen[d] for d in sorted(seen)]

    def _daily_window(self, symbol: str, start: dt.date, end: dt.date) -> list[Candle]:
        api = self.api
        self._limiter.acquire()

        def _fetch() -> dict[str, Any]:
            try:
                return _call()
            except Exception as exc:
                message = str(exc).lower()
                if any(m in message for m in PERMANENT_ERROR_MARKERS):
                    raise UnknownSymbol(str(exc)) from exc
                raise

        def _call() -> dict[str, Any]:
            with warnings.catch_warnings():
                # The replacement endpoint returns a null open for daily equity
                # candles, so the deprecated one is genuinely the better source.
                warnings.simplefilter("ignore", DeprecationWarning)
                return api.get_historical_candle_data(
                    trading_symbol=symbol,
                    exchange=api.EXCHANGE_NSE,
                    segment=api.SEGMENT_CASH,
                    start_time=f"{start:%Y-%m-%d} 09:15:00",
                    end_time=f"{end:%Y-%m-%d} 15:30:00",
                    interval_in_minutes=1440,
                )

        try:
            resp = retry_call(_fetch, label=f"groww.candles.{symbol}", give_up_on=(UnknownSymbol,))
            rows = resp.get("candles") or []
            return [
                Candle(
                    date=dt.datetime.fromtimestamp(r[0], dt.UTC).date(),
                    open=_f(r[1]),
                    high=_f(r[2]) or 0.0,
                    low=_f(r[3]) or 0.0,
                    close=_f(r[4]) or 0.0,
                    volume=_f(r[5]) or 0.0,
                )
                for r in rows
                if r and r[4] is not None
            ]
        except UnknownSymbol as exc:
            log.warning("groww.candles.unknown_symbol", symbol=symbol, error=str(exc)[:120])
            raise
        except Exception as exc:
            log.warning("groww.candles.failed", symbol=symbol, error=str(exc)[:200])
            return self._daily_window_fallback(symbol, start, end)

    def _daily_window_fallback(self, symbol: str, start: dt.date, end: dt.date) -> list[Candle]:
        """Current endpoint. Caps at 180 days and gives no open, so it is only
        used if the deprecated endpoint is withdrawn."""
        api = self.api
        out: list[Candle] = []
        cursor = start
        while cursor <= end:
            window_end = min(end, cursor + dt.timedelta(days=175))
            self._limiter.acquire()
            try:
                resp = retry_call(
                    lambda c=cursor, w=window_end: api.get_historical_candles(  # type: ignore[misc]
                        exchange=api.EXCHANGE_NSE,
                        segment=api.SEGMENT_CASH,
                        groww_symbol=f"NSE-{symbol}",
                        start_time=f"{c:%Y-%m-%d} 09:15:00",
                        end_time=f"{w:%Y-%m-%d} 15:30:00",
                        candle_interval=api.CANDLE_INTERVAL_DAY,
                    ),
                    label=f"groww.candles.fallback.{symbol}",
                )
                for r in resp.get("candles") or []:
                    if not r or r[4] is None:
                        continue
                    out.append(
                        Candle(
                            date=dt.datetime.fromisoformat(r[0]).date(),
                            open=_f(r[1]),
                            high=_f(r[2]) or 0.0,
                            low=_f(r[3]) or 0.0,
                            close=_f(r[4]) or 0.0,
                            volume=_f(r[5]) or 0.0,
                        )
                    )
            except Exception as exc:
                log.error("groww.candles.fallback_failed", symbol=symbol, error=str(exc)[:200])
            cursor = window_end + dt.timedelta(days=1)
        return out

    # ---- live quotes ------------------------------------------------------

    def ltp(self, symbols: list[str]) -> dict[str, float]:
        """Last traded price. The vendor accepts at most 50 symbols per call."""
        out: dict[str, float] = {}
        api = self.api
        for i in range(0, len(symbols), 50):
            chunk = symbols[i : i + 50]
            self._limiter.acquire()
            try:
                resp = retry_call(
                    lambda c=chunk: api.get_ltp(  # type: ignore[misc]
                        segment=api.SEGMENT_CASH,
                        exchange_trading_symbols=tuple(f"NSE_{s}" for s in c),
                    ),
                    label="groww.ltp",
                )
                for key, price in (resp or {}).items():
                    out[str(key).removeprefix("NSE_")] = float(price)
            except Exception as exc:
                log.warning("groww.ltp.failed", error=str(exc)[:200])
        return out


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
