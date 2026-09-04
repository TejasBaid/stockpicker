from __future__ import annotations

import json
import threading
import traceback
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import config, data, service
from app.backtest import run_backtest

app = FastAPI(title="Nifty Multi-Factor Screener API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_refresh_lock = threading.Lock()
_refresh_state = {"running": False, "message": None, "error": None}


class ScreenRequest(BaseModel):
    capital: float = Field(default=config.DEFAULT_CAPITAL, gt=0)
    top_n: int = Field(default=config.DEFAULT_TOP_N, ge=1, le=50)
    weights: Optional[dict] = None
    factor_mode: str = "all"
    max_per_sector: int = Field(default=config.DEFAULT_MAX_PER_SECTOR, ge=1, le=20)
    min_liquidity_cr: float = Field(default=config.DEFAULT_MIN_LIQUIDITY_CR, ge=0)
    require_uptrend: bool = True
    sectors: Optional[list[str]] = None


class BacktestRequest(BaseModel):
    capital: float = Field(default=config.DEFAULT_CAPITAL, gt=0)
    top_n: int = Field(default=config.DEFAULT_TOP_N, ge=1, le=50)
    weights: Optional[dict] = None
    max_per_sector: int = Field(default=config.DEFAULT_MAX_PER_SECTOR, ge=1, le=20)
    min_liquidity_cr: float = Field(default=config.DEFAULT_MIN_LIQUIDITY_CR, ge=0)


@app.get("/api/status")
def get_status():
    status = data.cache_status()
    status["refreshing"] = _refresh_state["running"]
    status["refresh_message"] = _refresh_state["message"]
    status["refresh_error"] = _refresh_state["error"]
    return status


def _do_refresh():
    try:
        _refresh_state["running"] = True
        _refresh_state["error"] = None

        def cb(msg):
            _refresh_state["message"] = msg

        data.refresh_all(progress_cb=cb)
    except Exception as e:
        _refresh_state["error"] = str(e)
        traceback.print_exc()
    finally:
        _refresh_state["running"] = False


@app.post("/api/refresh")
def refresh():
    if _refresh_state["running"]:
        return {"status": "already_running"}
    thread = threading.Thread(target=_do_refresh, daemon=True)
    thread.start()
    return {"status": "started"}


@app.get("/api/regime")
def get_regime():
    try:
        return service.get_regime()
    except FileNotFoundError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/screen")
def screen(req: ScreenRequest):
    try:
        return service.run_screen(
            capital=req.capital,
            top_n=req.top_n,
            weights=req.weights,
            factor_mode=req.factor_mode,
            max_per_sector=req.max_per_sector,
            min_liquidity_cr=req.min_liquidity_cr,
            require_uptrend=req.require_uptrend,
            sectors=req.sectors,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sectors")
def get_sectors():
    try:
        return {"sectors": service.list_sectors()}
    except FileNotFoundError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/api/stock-search")
def stock_search(q: str = ""):
    try:
        return {"results": service.search_stocks(q)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/api/stock/{ticker}")
def stock_detail(ticker: str, factor_mode: str = "all", weights: Optional[str] = None):
    try:
        parsed_weights = json.loads(weights) if weights else None
        return service.get_stock_detail(ticker, weights=parsed_weights, factor_mode=factor_mode)
    except FileNotFoundError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="weights must be a JSON object")


@app.post("/api/backtest")
def backtest(req: BacktestRequest):
    try:
        prices, volumes, fundamentals = data.load_cached()
        meta = data.load_universe_meta()
        if "sector" not in fundamentals.columns:
            fundamentals = fundamentals.copy()
            fundamentals["sector"] = "Unknown"
        fundamentals["sector"] = fundamentals["sector"].fillna(meta["csv_industry"]).fillna("Unknown")

        w = {**config.DEFAULT_WEIGHTS, **(req.weights or {})}
        result = run_backtest(
            prices, volumes, fundamentals, w,
            top_n=req.top_n, capital=req.capital,
            max_per_sector=req.max_per_sector,
            min_liquidity_cr=req.min_liquidity_cr,
        )
        if not result:
            raise HTTPException(status_code=422, detail="Not enough price history for a backtest (need ~15+ months cached).")
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/api/config")
def get_config():
    return {
        "default_weights": config.DEFAULT_WEIGHTS,
        "default_capital": config.DEFAULT_CAPITAL,
        "default_top_n": config.DEFAULT_TOP_N,
        "default_max_per_sector": config.DEFAULT_MAX_PER_SECTOR,
        "default_min_liquidity_cr": config.DEFAULT_MIN_LIQUIDITY_CR,
        "horizon_weights": config.HORIZON_WEIGHTS,
        "risk_profiles": config.RISK_PROFILE_ADJUSTMENTS,
        "strategies": config.STRATEGIES,
    }
