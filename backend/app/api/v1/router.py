from fastapi import APIRouter

from app.api.v1 import auth, backtests, data, portfolio, screener, strategies

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(data.router)
api_router.include_router(screener.router)
api_router.include_router(backtests.router)
api_router.include_router(portfolio.router)
api_router.include_router(strategies.router)
