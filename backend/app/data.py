"""Universe loading, price/fundamentals fetching, and disk caching.

yfinance calls are slow and rate-limit-prone, so everything here is cached to
disk (parquet/json) with a TTL. The web API serves screens from cache and
only hits the network on an explicit /api/refresh call.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

from . import config

PRICES_CACHE = config.CACHE_DIR / "prices.parquet"
VOLUMES_CACHE = config.CACHE_DIR / "volumes.parquet"
FUNDAMENTALS_CACHE = config.CACHE_DIR / "fundamentals.parquet"
META_CACHE = config.CACHE_DIR / "meta.json"


def load_universe() -> list[str]:
    df = pd.read_csv(config.UNIVERSE_CSV)
    if "Symbol" not in df.columns:
        raise ValueError("universe.csv must have a 'Symbol' column")
    tickers = df["Symbol"].dropna().astype(str).str.strip().str.upper().tolist()
    return [f"{t}.NS" for t in tickers]


def load_universe_meta() -> pd.DataFrame:
    """Company name / industry lookup keyed by ticker (with .NS suffix)."""
    df = pd.read_csv(config.UNIVERSE_CSV)
    df["ticker"] = df["Symbol"].astype(str).str.strip().str.upper() + ".NS"
    return df.set_index("ticker")[["Company Name", "Industry"]].rename(
        columns={"Company Name": "csv_name", "Industry": "csv_industry"}
    )


def _read_meta() -> dict:
    if META_CACHE.exists():
        return json.loads(META_CACHE.read_text())
    return {}


def _write_meta(meta: dict) -> None:
    META_CACHE.write_text(json.dumps(meta, default=str))


def cache_status() -> dict:
    meta = _read_meta()
    now = datetime.now(timezone.utc)
    status = {"prices_fetched_at": None, "fundamentals_fetched_at": None,
              "prices_age_hours": None, "fundamentals_age_hours": None,
              "n_tickers": meta.get("n_tickers"), "ready": PRICES_CACHE.exists()}
    if meta.get("prices_fetched_at"):
        ts = datetime.fromisoformat(meta["prices_fetched_at"])
        status["prices_fetched_at"] = meta["prices_fetched_at"]
        status["prices_age_hours"] = round((now - ts).total_seconds() / 3600, 2)
    if meta.get("fundamentals_fetched_at"):
        ts = datetime.fromisoformat(meta["fundamentals_fetched_at"])
        status["fundamentals_fetched_at"] = meta["fundamentals_fetched_at"]
        status["fundamentals_age_hours"] = round((now - ts).total_seconds() / 3600, 2)
    return status


def fetch_prices_and_volumes(tickers: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Batch-download OHLCV for all tickers + the index in one yfinance call."""
    all_tickers = tickers + [config.INDEX_TICKER]
    raw = yf.download(
        all_tickers, period=config.PRICE_PERIOD, progress=False,
        auto_adjust=True, group_by="column", threads=True,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"]
        vols = raw["Volume"]
    else:
        closes = raw[["Close"]].rename(columns={"Close": all_tickers[0]})
        vols = raw[["Volume"]].rename(columns={"Volume": all_tickers[0]})
    closes = closes.ffill().dropna(how="all", axis=1)
    vols = vols.reindex(columns=closes.columns)
    return closes, vols


def _fetch_one_fundamental(ticker: str) -> dict:
    try:
        info = yf.Ticker(ticker).info
        return {
            "ticker": ticker,
            "pe": info.get("trailingPE"),
            "pb": info.get("priceToBook"),
            "roe": info.get("returnOnEquity"),
            "debt_equity": info.get("debtToEquity"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "profit_margin": info.get("profitMargins"),
            "current_ratio": info.get("currentRatio"),
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector") or "Unknown",
            "industry": info.get("industry") or "Unknown",
            "name": info.get("shortName") or ticker,
        }
    except Exception:
        return {"ticker": ticker}


def fetch_fundamentals(tickers: list[str], max_workers: int = 12) -> pd.DataFrame:
    records = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_fetch_one_fundamental, t) for t in tickers]
        for fut in as_completed(futures):
            records.append(fut.result())
    df = pd.DataFrame(records).set_index("ticker")
    return df.reindex(tickers)


def refresh_all(progress_cb=None) -> dict:
    """Full network refresh: prices, volumes, fundamentals -> disk cache."""
    t0 = time.time()
    tickers = load_universe()
    if progress_cb:
        progress_cb(f"Downloading price history for {len(tickers)} symbols...")
    prices, volumes = fetch_prices_and_volumes(tickers)

    min_obs = config.MIN_HISTORY
    prices = prices.loc[:, prices.notna().sum() >= min_obs]
    volumes = volumes.reindex(columns=prices.columns)

    stock_cols = [c for c in prices.columns if c != config.INDEX_TICKER]
    if progress_cb:
        progress_cb(f"Downloading fundamentals for {len(stock_cols)} stocks...")
    fundamentals = fetch_fundamentals(stock_cols)

    prices.to_parquet(PRICES_CACHE)
    volumes.to_parquet(VOLUMES_CACHE)
    fundamentals.to_parquet(FUNDAMENTALS_CACHE)

    meta = _read_meta()
    now = datetime.now(timezone.utc).isoformat()
    meta["prices_fetched_at"] = now
    meta["fundamentals_fetched_at"] = now
    meta["n_tickers"] = len(stock_cols)
    _write_meta(meta)

    elapsed = round(time.time() - t0, 1)
    if progress_cb:
        progress_cb(f"Done in {elapsed}s ({len(stock_cols)} stocks cached).")
    return {"n_tickers": len(stock_cols), "elapsed_seconds": elapsed}


def load_cached() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not PRICES_CACHE.exists():
        raise FileNotFoundError("No cached data yet. Call /api/refresh first.")
    prices = pd.read_parquet(PRICES_CACHE)
    volumes = pd.read_parquet(VOLUMES_CACHE) if VOLUMES_CACHE.exists() else pd.DataFrame(index=prices.index, columns=prices.columns)
    fundamentals = pd.read_parquet(FUNDAMENTALS_CACHE) if FUNDAMENTALS_CACHE.exists() else pd.DataFrame(index=[c for c in prices.columns if c != config.INDEX_TICKER])
    return prices, volumes, fundamentals
