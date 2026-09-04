"""FastAPI application entrypoint.

The request path deliberately does no heavy computation: factors are
precomputed by the nightly worker and backtests run as queued jobs elsewhere,
so this process only reads SQL and serves JSON.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import engine

settings = get_settings()
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Nifty 200 Screener",
    version="0.1.0",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(RequestValidationError)
def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's default 422 body is a list of error objects, which a UI cannot
    show to a person. Collapse it into one readable sentence naming the fields,
    so `detail` is always a string across the whole API."""
    parts: list[str] = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err.get("loc", ()) if p != "body") or "request"
        message = str(err.get("msg", "is invalid")).removeprefix("Value error, ")
        parts.append(f"{field}: {message}")
    return JSONResponse(status_code=422, content={"detail": "; ".join(parts)})


@app.get("/health", tags=["ops"])
def health() -> dict[str, object]:
    """Also the warm-up target for the uptime pinger during market hours."""
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}


app.include_router(api_router)
