"""All ORM models. Importing this module registers every table on Base.metadata."""

from app.db.models.auth import Invite, User, UserSession
from app.db.models.factors import FactorCoverage, FactorValue
from app.db.models.fundamentals import (
    Announcement,
    CorporateAction,
    Estimate,
    FinancialStatement,
    FundamentalSnapshot,
    PriceTarget,
    Shareholding,
    ValuationHistory,
)
from app.db.models.market import DailyBar, Instrument, Universe, UniverseMember
from app.db.models.ops import IngestRun, ProviderCallDaily
from app.db.models.portfolio import (
    Alert,
    ExitPlan,
    Portfolio,
    Position,
    Trade,
    Watchlist,
    WatchlistItem,
)
from app.db.models.research import BacktestJob, ScreenRun, Strategy

__all__ = [
    "Alert",
    "Announcement",
    "BacktestJob",
    "CorporateAction",
    "DailyBar",
    "Estimate",
    "ExitPlan",
    "FactorCoverage",
    "FactorValue",
    "FinancialStatement",
    "FundamentalSnapshot",
    "IngestRun",
    "Instrument",
    "Invite",
    "Portfolio",
    "Position",
    "PriceTarget",
    "ProviderCallDaily",
    "ScreenRun",
    "Shareholding",
    "Strategy",
    "Trade",
    "Universe",
    "UniverseMember",
    "User",
    "UserSession",
    "ValuationHistory",
    "Watchlist",
    "WatchlistItem",
]
