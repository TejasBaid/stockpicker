"""
╔══════════════════════════════════════════════════════════════════════╗
║         NIFTY 200 MULTI-FACTOR SYSTEMATIC SCREENER                  ║
║         Momentum · Quality · Value · Volatility · Regime            ║
╚══════════════════════════════════════════════════════════════════════╝

Usage:
    python nifty_screener.py                          # Full run, default ₹2L
    python nifty_screener.py --capital 150000         # Custom capital
    python nifty_screener.py --top 8 --export         # Top 8 + CSV export
    python nifty_screener.py --factor momentum        # Single-factor mode
    python nifty_screener.py --backtest               # Rolling backtest

Requirements:
    pip install yfinance rich pandas numpy scipy scikit-learn statsmodels
    Place 'ind_nifty200list.csv' (with 'Symbol' column) in same directory.
    If CSV is absent, falls back to a hardcoded Nifty 50 universe.
"""

import argparse
import os
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from export_excel import export_to_excel
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table
from rich import box
from rich.text import Text
from scipy import stats

warnings.simplefilter(action="ignore", category=FutureWarning)
warnings.simplefilter(action="ignore", category=RuntimeWarning)
pd.options.mode.chained_assignment = None

console = Console()

# ── Fallback universe if CSV is missing ───────────────────────────────────────
NIFTY50_FALLBACK = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "HCLTECH", "ASIANPAINT", "AXISBANK", "BAJFINANCE",
    "MARUTI", "ULTRACEMCO", "TITAN", "WIPRO", "SUNPHARMA",
    "NESTLEIND", "POWERGRID", "NTPC", "TATAMOTORS", "ONGC",
    "TECHM", "BAJAJFINSV", "JSWSTEEL", "TATASTEEL", "ADANIENT",
    "GRASIM", "HINDALCO", "CIPLA", "DRREDDY", "DIVISLAB",
    "BPCL", "EICHERMOT", "COALINDIA", "BRITANNIA", "HEROMOTOCO",
    "ADANIPORTS", "APOLLOHOSP", "SBILIFE", "HDFCLIFE", "BAJAJ-AUTO",
    "UPL", "TATACONSUM", "INDUSINDBK", "MM", "LTIM",
]


# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════
class Config:
    CSV_FILE        = "ind_nifty200list.csv"
    INDEX_TICKER    = "^NSEI"
    LOOKBACK_DAYS   = 252       # 12-month formation window
    SKIP_DAYS       = 21        # Skip last month (avoid short-term reversal)
    SHORT_MOM_DAYS  = 63        # 3-month short momentum
    REGIME_SMA      = 200       # Market regime: Nifty 50 vs 200-SMA
    REGIME_SMA_FAST = 50        # Secondary regime signal
    MIN_HISTORY     = 300       # Min trading days to include a stock
    REBAL_FREQ      = "QE"      # Quarterly rebalance for backtest (pandas 2.2+)

    # Factor weights (must sum to 1.0)
    WEIGHTS = {
        "momentum":  0.35,
        "quality":   0.25,
        "value":     0.20,
        "low_vol":   0.20,
    }

    # Risk controls
    MAX_SINGLE_WEIGHT = 0.20    # No stock > 20% of portfolio
    MIN_SINGLE_WEIGHT = 0.05    # No stock < 5% of portfolio


# ══════════════════════════════════════════════════════════════════════════════
# DATA LAYER
# ══════════════════════════════════════════════════════════════════════════════
def load_universe(csv_file: str) -> list[str]:
    """Load tickers from CSV or fall back to Nifty 50 hardcoded list."""
    if os.path.exists(csv_file):
        df = pd.read_csv(csv_file)
        if "Symbol" not in df.columns:
            console.print("[red]CSV must have a 'Symbol' column. Using fallback universe.[/red]")
            tickers = NIFTY50_FALLBACK
        else:
            tickers = df["Symbol"].dropna().tolist()
            console.print(f"[green]✓[/green] Loaded {len(tickers)} symbols from {csv_file}")
    else:
        console.print(
            f"[yellow]⚠[/yellow]  {csv_file} not found — using Nifty 50 fallback universe "
            f"({len(NIFTY50_FALLBACK)} stocks)"
        )
        tickers = NIFTY50_FALLBACK

    return [t.strip().upper() + ".NS" for t in tickers]


def fetch_prices(tickers: list[str], period: str = "3y") -> pd.DataFrame:
    """Download adjusted close prices for all tickers + index."""
    all_tickers = tickers + [Config.INDEX_TICKER]
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        transient=True,
        console=console,
    ) as progress:
        task = progress.add_task(
            f"Fetching {len(all_tickers)} symbols ({period})…", total=None
        )
        raw = yf.download(all_tickers, period=period, progress=False, auto_adjust=True)
        progress.update(task, completed=True)

    prices = raw["Close"] if "Close" in raw else raw
    prices = prices.ffill().dropna(how="all", axis=1)
    return prices


def fetch_fundamentals(tickers: list[str]) -> pd.DataFrame:
    """
    Pull key fundamental metrics via yfinance .info.
    Returns a DataFrame indexed by ticker with columns:
        pe, pb, roe, debt_equity, revenue_growth, profit_margin, current_ratio
    """
    records = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        task = progress.add_task(
            f"Fetching fundamentals for {len(tickers)} stocks…", total=len(tickers)
        )
        for ticker in tickers:
            try:
                info = yf.Ticker(ticker).info
                records.append({
                    "ticker":          ticker,
                    "pe":              info.get("trailingPE"),
                    "pb":              info.get("priceToBook"),
                    "roe":             info.get("returnOnEquity"),
                    "debt_equity":     info.get("debtToEquity"),
                    "revenue_growth":  info.get("revenueGrowth"),
                    "profit_margin":   info.get("profitMargins"),
                    "current_ratio":   info.get("currentRatio"),
                    "market_cap":      info.get("marketCap"),
                    "sector":          info.get("sector", "Unknown"),
                    "name":            info.get("shortName", ticker),
                })
            except Exception:
                records.append({"ticker": ticker})
            progress.update(task, advance=1)

    df = pd.DataFrame(records).set_index("ticker")
    return df


# ══════════════════════════════════════════════════════════════════════════════
# FACTOR ENGINES
# ══════════════════════════════════════════════════════════════════════════════
def zscore(series: pd.Series) -> pd.Series:
    """Cross-sectional z-score (winsorized at ±3σ)."""
    s = series.dropna()
    z = (s - s.mean()) / s.std()
    return z.clip(-3, 3).reindex(series.index)


def factor_momentum(prices: pd.DataFrame) -> pd.Series:
    """
    Risk-adjusted momentum = (12m-1m return) / annualised vol.
    Blended 50/50 with 3-month momentum to capture both intermediate
    and short-term trend.
    """
    lb, sk, sh = Config.LOOKBACK_DAYS, Config.SKIP_DAYS, Config.SHORT_MOM_DAYS

    if len(prices) < lb + 5:
        return pd.Series(dtype=float)

    p_now  = prices.iloc[-1]
    p_skip = prices.iloc[-(sk + 1)]
    p_12m  = prices.iloc[-(lb + 1)]
    p_3m   = prices.iloc[-(sh + 1)]

    mom_12_1 = (p_skip / p_12m) - 1        # Classic 12-1 momentum
    mom_3    = (p_now  / p_3m)  - 1        # 3-month short momentum

    daily_ret    = prices.iloc[-lb:].pct_change()
    ann_vol      = daily_ret.std() * np.sqrt(252)
    risk_adj_mom = mom_12_1 / ann_vol.replace(0, np.nan)

    # Blend: 70% risk-adjusted 12m1m + 30% 3m
    blended = 0.70 * zscore(risk_adj_mom) + 0.30 * zscore(mom_3)
    return zscore(blended)


def factor_quality(fundamentals: pd.DataFrame) -> pd.Series:
    """
    Quality score = composite of:
      - Return on Equity (high = good)
      - Profit margin   (high = good)
      - Debt/Equity     (low  = good, inverted)
      - Current ratio   (high = good, capped at 3)
    """
    df = fundamentals.copy()

    roe_z     =  zscore(df["roe"])
    margin_z  =  zscore(df["profit_margin"])
    debt_z    = -zscore(df["debt_equity"])        # Invert: less debt = better
    cr        =  df["current_ratio"].clip(upper=3)
    cr_z      =  zscore(cr)

    quality = (0.35 * roe_z + 0.30 * margin_z + 0.25 * debt_z + 0.10 * cr_z)
    return zscore(quality)


def factor_value(fundamentals: pd.DataFrame) -> pd.Series:
    """
    Value score = composite of:
      - Earnings yield = 1/PE  (high = cheap)
      - P/B inverted           (low PB = cheap)
    Both winsorized to avoid distortion from negative-PE stocks.
    """
    df = fundamentals.copy()

    # Earnings yield: only for stocks with positive PE
    ey = (1 / df["pe"]).where(df["pe"] > 0)
    ey_z  = zscore(ey)
    pb_z  = -zscore(df["pb"].clip(lower=0.1))    # Invert PB

    value = 0.60 * ey_z + 0.40 * pb_z
    return zscore(value)


def factor_low_volatility(prices: pd.DataFrame) -> pd.Series:
    """
    Low volatility score = negative of annualised 252-day realised vol.
    Stocks with lower vol get a higher score (defensive tilt).
    Also incorporates 63-day beta vs Nifty for market-relative risk.
    """
    if len(prices) < Config.LOOKBACK_DAYS:
        return pd.Series(dtype=float)

    daily_ret = prices.iloc[-Config.LOOKBACK_DAYS:].pct_change()
    ann_vol   = daily_ret.std() * np.sqrt(252)
    vol_z     = -zscore(ann_vol)               # Invert: low vol = high score

    # Beta component
    if Config.INDEX_TICKER in daily_ret.columns:
        idx_ret  = daily_ret[Config.INDEX_TICKER].dropna()
        stock_ret = daily_ret.drop(columns=[Config.INDEX_TICKER], errors="ignore")
        betas = {}
        for col in stock_ret.columns:
            s = stock_ret[col].dropna()
            aligned = pd.concat([s, idx_ret], axis=1).dropna()
            if len(aligned) > 60:
                b, _, _, _, _ = stats.linregress(aligned.iloc[:, 1], aligned.iloc[:, 0])
                betas[col] = b
        beta_series = pd.Series(betas)
        beta_z = -zscore(beta_series)          # Invert: low beta = high score
        combined = 0.60 * vol_z + 0.40 * beta_z.reindex(vol_z.index)
    else:
        combined = vol_z

    return zscore(combined)


# ══════════════════════════════════════════════════════════════════════════════
# MARKET REGIME FILTER
# ══════════════════════════════════════════════════════════════════════════════
class RegimeState:
    GREEN  = "GREEN"
    YELLOW = "YELLOW"
    RED    = "RED"


def detect_regime(index_prices: pd.Series) -> dict:
    """
    Three-state regime filter using dual SMA crossover + breadth proxy.
      GREEN  → Full deployment
      YELLOW → 50% deployment, tilt to low-vol
      RED    → Hold cash / short-term bonds only
    """
    sma200  = index_prices.rolling(200).mean().iloc[-1]
    sma50   = index_prices.rolling(50).mean().iloc[-1]
    current = index_prices.iloc[-1]

    # 1-month and 3-month returns for trend slope
    ret_1m = (current / index_prices.iloc[-22])  - 1
    ret_3m = (current / index_prices.iloc[-63])  - 1

    # Annualised vol of the index itself
    idx_vol = index_prices.pct_change().iloc[-63:].std() * np.sqrt(252)

    above_200 = current > sma200
    above_50  = current > sma50
    golden_cross = sma50 > sma200        # 50 SMA above 200 SMA

    if above_200 and above_50 and golden_cross:
        state = RegimeState.GREEN
        deploy_pct = 1.00
    elif above_200 and not above_50:
        state = RegimeState.YELLOW
        deploy_pct = 0.65
    else:
        state = RegimeState.RED
        deploy_pct = 0.25

    return {
        "state":       state,
        "deploy_pct":  deploy_pct,
        "current":     current,
        "sma50":       sma50,
        "sma200":      sma200,
        "ret_1m":      ret_1m,
        "ret_3m":      ret_3m,
        "idx_vol":     idx_vol,
        "above_200":   above_200,
        "golden_cross": golden_cross,
    }


# ══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO CONSTRUCTION
# ══════════════════════════════════════════════════════════════════════════════
def build_composite_score(
    prices: pd.DataFrame,
    fundamentals: pd.DataFrame,
    factor_mode: str = "all",
) -> pd.DataFrame:
    """
    Compute all factor scores and blend into a single composite.
    factor_mode: 'all' | 'momentum' | 'quality' | 'value' | 'low_vol'
    """
    stock_prices = prices.drop(columns=[Config.INDEX_TICKER], errors="ignore")

    with console.status("Computing momentum factor…"):
        f_mom = factor_momentum(stock_prices)
    with console.status("Computing low-volatility factor…"):
        f_vol = factor_low_volatility(prices)  # pass full (includes index for beta)
    with console.status("Computing quality factor…"):
        f_qual = factor_quality(fundamentals)
    with console.status("Computing value factor…"):
        f_val  = factor_value(fundamentals)

    scores = pd.DataFrame({
        "momentum": f_mom,
        "quality":  f_qual.reindex(f_mom.index),
        "value":    f_val.reindex(f_mom.index),
        "low_vol":  f_vol.reindex(f_mom.index),
    })

    if factor_mode != "all" and factor_mode in scores.columns:
        scores["composite"] = scores[factor_mode]
    else:
        w = Config.WEIGHTS
        scores["composite"] = (
            w["momentum"] * scores["momentum"].fillna(0) +
            w["quality"]  * scores["quality"].fillna(0)  +
            w["value"]    * scores["value"].fillna(0)    +
            w["low_vol"]  * scores["low_vol"].fillna(0)
        )

    return scores


def inverse_volatility_weights(
    tickers: list[str],
    prices: pd.DataFrame,
    top_n: int,
) -> pd.Series:
    """
    Compute inverse-volatility weights for selected tickers,
    clamped within [MIN_SINGLE_WEIGHT, MAX_SINGLE_WEIGHT].
    """
    stock_prices = prices[tickers].iloc[-Config.LOOKBACK_DAYS:]
    ann_vol = stock_prices.pct_change().std() * np.sqrt(252)
    inv_vol = 1 / ann_vol.replace(0, np.nan)
    raw_w   = inv_vol / inv_vol.sum()

    # Clamp and renormalize iteratively (max 20 passes)
    w = raw_w.copy()
    for _ in range(20):
        w = w.clip(Config.MIN_SINGLE_WEIGHT, Config.MAX_SINGLE_WEIGHT)
        w = w / w.sum()
        if (w == w.clip(Config.MIN_SINGLE_WEIGHT, Config.MAX_SINGLE_WEIGHT)).all():
            break
    return w


def construct_portfolio(
    scores: pd.DataFrame,
    prices: pd.DataFrame,
    fundamentals: pd.DataFrame,
    capital: float,
    top_n: int,
    regime: dict,
) -> pd.DataFrame:
    """Select top-N stocks, size positions, compute trade instructions."""

    # Adjust capital for regime
    effective_capital = capital * regime["deploy_pct"]

    # Rank and select top N by composite score
    ranked    = scores.dropna(subset=["composite"]).sort_values("composite", ascending=False)
    selected  = ranked.head(top_n).index.tolist()

    # Only keep tickers with price data
    valid     = [t for t in selected if t in prices.columns]
    weights   = inverse_volatility_weights(valid, prices, top_n)

    current_px = prices[valid].iloc[-1]

    port = pd.DataFrame({
        "weight":         weights,
        "alloc_capital":  weights * effective_capital,
        "close_price":    current_px,
    })

    port["shares"]       = np.floor(port["alloc_capital"] / port["close_price"])
    port["actual_cost"]  = port["shares"] * port["close_price"]
    port["momentum_z"]   = scores.loc[valid, "momentum"]
    port["quality_z"]    = scores.loc[valid, "quality"]
    port["value_z"]      = scores.loc[valid, "value"]
    port["low_vol_z"]    = scores.loc[valid, "low_vol"]
    port["composite_z"]  = scores.loc[valid, "composite"]

    # Merge fundamentals for display
    for col in ["name", "sector", "pe", "pb", "roe"]:
        if col in fundamentals.columns:
            port[col] = fundamentals[col].reindex(port.index)

    port.index = port.index.str.replace(".NS", "", regex=False)
    return port


# ══════════════════════════════════════════════════════════════════════════════
# BACKTEST ENGINE
# ══════════════════════════════════════════════════════════════════════════════
def run_backtest(
    prices_full: pd.DataFrame,
    fundamentals: pd.DataFrame,
    top_n: int = 10,
    capital: float = 200_000,
) -> dict:
    """
    Rolling quarterly backtest over the available price history.
    Uses only data available up to each rebalance date (no lookahead).
    Returns dict with equity curve, CAGR, Sharpe, MaxDD, etc.
    """
    console.print("\n[bold]Running rolling backtest (quarterly rebalance)…[/bold]")

    stock_prices = prices_full.drop(columns=[Config.INDEX_TICKER], errors="ignore")

    # Need at least LOOKBACK_DAYS + 1 quarter of data
    min_rows = Config.LOOKBACK_DAYS + 65
    if len(prices_full) < min_rows:
        console.print("[red]Not enough data for backtest. Need at least 15 months.[/red]")
        return {}

    start_idx = Config.LOOKBACK_DAYS + 1
    rebal_dates = pd.date_range(
        stock_prices.index[start_idx],
        stock_prices.index[-1],
        freq=Config.REBAL_FREQ,
    )
    rebal_dates = [d for d in rebal_dates if d in stock_prices.index]

    equity   = [capital]
    dates    = [stock_prices.index[start_idx]]
    holdings = {}  # ticker -> shares

    for i, rebal_date in enumerate(rebal_dates):
        loc = stock_prices.index.get_loc(rebal_date)
        slice_prices = prices_full.iloc[: loc + 1]

        # Regime at this point in time
        idx_slice = slice_prices[Config.INDEX_TICKER].dropna()
        if len(idx_slice) < 200:
            continue
        regime = detect_regime(idx_slice)

        scores = build_composite_score(slice_prices, fundamentals)

        ranked = scores.dropna(subset=["composite"]).sort_values("composite", ascending=False)
        selected = [t for t in ranked.head(top_n).index if t in slice_prices.columns]
        if not selected:
            continue

        # Compute portfolio value at rebalance date
        port_value = sum(
            holdings.get(t, 0) * slice_prices[t].iloc[-1]
            for t in holdings
        )
        if port_value == 0:
            port_value = equity[-1]

        effective_val = port_value * regime["deploy_pct"]
        weights = inverse_volatility_weights(selected, slice_prices, top_n)

        holdings = {}
        for t in selected:
            w   = weights.get(t, 0)
            px  = slice_prices[t].iloc[-1]
            holdings[t] = np.floor(w * effective_val / px)

        # Simulate daily P&L until next rebalance
        next_rebal = rebal_dates[i + 1] if i + 1 < len(rebal_dates) else stock_prices.index[-1]
        sim_slice  = stock_prices.loc[rebal_date:next_rebal, list(holdings.keys())].dropna(how="all", axis=1)

        for day in sim_slice.index[1:]:
            day_val = sum(holdings.get(t, 0) * sim_slice.loc[day, t]
                          for t in holdings if t in sim_slice.columns)
            equity.append(day_val)
            dates.append(day)

    equity_series = pd.Series(equity, index=dates).sort_index()

    # ── Performance metrics ──────────────────────────────────────────────────
    total_days = (equity_series.index[-1] - equity_series.index[0]).days
    n_years    = total_days / 365.25
    cagr       = (equity_series.iloc[-1] / equity_series.iloc[0]) ** (1 / n_years) - 1

    daily_ret  = equity_series.pct_change().dropna()
    sharpe     = (daily_ret.mean() / daily_ret.std()) * np.sqrt(252) if daily_ret.std() > 0 else 0

    # Max drawdown
    roll_max   = equity_series.cummax()
    drawdown   = (equity_series - roll_max) / roll_max
    max_dd     = drawdown.min()

    # Calmar ratio
    calmar     = cagr / abs(max_dd) if max_dd != 0 else 0

    # Sortino (downside dev)
    neg_ret    = daily_ret[daily_ret < 0]
    sortino    = (daily_ret.mean() / neg_ret.std()) * np.sqrt(252) if len(neg_ret) > 0 else 0

    # Nifty benchmark
    idx_full   = prices_full[Config.INDEX_TICKER].loc[equity_series.index[0]:equity_series.index[-1]]
    bench_cagr = (idx_full.iloc[-1] / idx_full.iloc[0]) ** (1 / n_years) - 1 if len(idx_full) > 1 else 0

    return {
        "equity":      equity_series,
        "cagr":        cagr,
        "bench_cagr":  bench_cagr,
        "sharpe":      sharpe,
        "sortino":     sortino,
        "max_dd":      max_dd,
        "calmar":      calmar,
        "n_years":     n_years,
        "final_val":   equity_series.iloc[-1],
        "start_val":   equity_series.iloc[0],
    }


# ══════════════════════════════════════════════════════════════════════════════
# DISPLAY LAYER
# ══════════════════════════════════════════════════════════════════════════════
def print_header():
    console.print(Panel.fit(
        "[bold cyan]NIFTY 200 MULTI-FACTOR SYSTEMATIC SCREENER[/bold cyan]\n"
        "[dim]Momentum · Quality · Value · Low-Volatility · Regime Filter[/dim]",
        border_style="cyan"
    ))
    console.print()


def print_regime(regime: dict):
    state = regime["state"]
    colour = {"GREEN": "green", "YELLOW": "yellow", "RED": "red"}[state]
    icon   = {"GREEN": "✅", "YELLOW": "⚠️", "RED": "🚨"}[state]
    label  = {
        "GREEN":  "BULL — Full deployment",
        "YELLOW": "CAUTION — Partial deployment (65%)",
        "RED":    "BEAR — Capital protection mode (25%)",
    }[state]

    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    t.add_column("k", style="dim", min_width=28)
    t.add_column("v", style="bold")

    t.add_row("Nifty 50 Current",  f"₹{regime['current']:,.2f}")
    t.add_row("50-Day SMA",        f"₹{regime['sma50']:,.2f}")
    t.add_row("200-Day SMA",       f"₹{regime['sma200']:,.2f}")
    t.add_row("1-Month Return",    f"{regime['ret_1m']*100:+.2f}%")
    t.add_row("3-Month Return",    f"{regime['ret_3m']*100:+.2f}%")
    t.add_row("Index Volatility",  f"{regime['idx_vol']*100:.1f}% p.a.")
    t.add_row("Golden Cross",      "Yes ✅" if regime["golden_cross"] else "No ❌")
    t.add_row("Deploy %",          f"{regime['deploy_pct']*100:.0f}%")

    console.print(Panel(
        t,
        title=f"[{colour}]{icon}  MARKET REGIME: {label}[/{colour}]",
        border_style=colour,
    ))
    console.print()


def print_factor_weights():
    t = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
    t.add_column("Factor", style="bold")
    t.add_column("Weight", justify="right")
    t.add_column("What it captures")

    rows = [
        ("Momentum",     f"{Config.WEIGHTS['momentum']*100:.0f}%", "12m-1m risk-adj + 3m trend blend"),
        ("Quality",      f"{Config.WEIGHTS['quality']*100:.0f}%",  "ROE, margins, debt, current ratio"),
        ("Value",        f"{Config.WEIGHTS['value']*100:.0f}%",    "Earnings yield + inverse P/B"),
        ("Low Volatility",f"{Config.WEIGHTS['low_vol']*100:.0f}%","Ann. vol + CAPM beta vs Nifty"),
    ]
    for r in rows:
        t.add_row(*r)

    console.print(Panel(t, title="Factor Model Configuration", border_style="blue"))
    console.print()


def print_portfolio(port: pd.DataFrame, capital: float, regime: dict, top_n: int):
    effective_capital = capital * regime["deploy_pct"]
    total_deployed    = port["actual_cost"].sum()
    cash_remaining    = capital - total_deployed
    cash_buffer       = capital - effective_capital  # regime-held cash

    t = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
        title=f"[bold]Top {top_n} Stocks  |  ₹{capital:,.0f} Capital  |  Regime: {regime['state']}[/bold]",
        caption=f"Deployed: ₹{total_deployed:,.0f}  |  Cash: ₹{cash_remaining:,.0f}  |  Regime buffer: ₹{cash_buffer:,.0f}",
    )

    t.add_column("#",           justify="right",  style="dim", width=3)
    t.add_column("Ticker",      style="bold cyan", min_width=12)
    t.add_column("Name",        min_width=18, max_width=22, no_wrap=True)
    t.add_column("Sector",      min_width=14, max_width=18, no_wrap=True)
    t.add_column("Wt %",        justify="right")
    t.add_column("Price ₹",     justify="right")
    t.add_column("Shares",      justify="right")
    t.add_column("Cost ₹",      justify="right")
    t.add_column("Mom Z",       justify="right")
    t.add_column("Qual Z",      justify="right")
    t.add_column("Val Z",       justify="right")
    t.add_column("Vol Z",       justify="right")
    t.add_column("Comp Z",      justify="right", style="bold")

    def z_fmt(val):
        if pd.isna(val):
            return "[dim]—[/dim]"
        col = "green" if val > 0.5 else ("red" if val < -0.5 else "yellow")
        return f"[{col}]{val:+.2f}[/{col}]"

    for i, (idx, row) in enumerate(port.iterrows(), 1):
        t.add_row(
            str(i),
            idx,
            str(row.get("name", "—"))[:22],
            str(row.get("sector", "—"))[:18],
            f"{row['weight']*100:.1f}%",
            f"{row['close_price']:,.2f}",
            f"{int(row['shares'])}",
            f"₹{row['actual_cost']:,.0f}",
            z_fmt(row.get("momentum_z")),
            z_fmt(row.get("quality_z")),
            z_fmt(row.get("value_z")),
            z_fmt(row.get("low_vol_z")),
            z_fmt(row.get("composite_z")),
        )

    console.print(t)
    console.print()


def print_backtest(bt: dict):
    if not bt:
        return

    alpha = bt["cagr"] - bt["bench_cagr"]
    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column("Metric", style="dim", min_width=26)
    t.add_column("Strategy", style="bold")
    t.add_column("Benchmark (Nifty)")

    def pct(v): return f"{v*100:.2f}%"
    def signed_pct(v): color = "green" if v > 0 else "red"; return f"[{color}]{v*100:+.2f}%[/{color}]"

    t.add_row("Period (years)",    f"{bt['n_years']:.1f}", "—")
    t.add_row("Starting Capital",  f"₹{bt['start_val']:,.0f}", "—")
    t.add_row("Final Value",       f"₹{bt['final_val']:,.0f}", "—")
    t.add_row("CAGR",              signed_pct(bt["cagr"]),    pct(bt["bench_cagr"]))
    t.add_row("Alpha vs Nifty",    signed_pct(alpha),         "—")
    t.add_row("Sharpe Ratio",      f"{bt['sharpe']:.2f}",     "—")
    t.add_row("Sortino Ratio",     f"{bt['sortino']:.2f}",    "—")
    t.add_row("Max Drawdown",      f"[red]{bt['max_dd']*100:.2f}%[/red]", "—")
    t.add_row("Calmar Ratio",      f"{bt['calmar']:.2f}",     "—")

    console.print(Panel(t, title="📈 Backtest Results (Quarterly Rebalance)", border_style="magenta"))
    console.print()


def print_rebalance_notes():
    notes = [
        ("Rebalance cadence",  "Quarterly (or when drift > 5% from target weight)"),
        ("Entry execution",    "Use LIMIT orders, not market. Check bid-ask spread."),
        ("Brokerage",          "Zerodha (₹0 equity delivery). Use Kite API for automation."),
        ("Tax (STCG)",         "Gains < 1 year taxed at 20%. Hold >1yr for 12.5% LTCG."),
        ("Liquidity filter",   "Avoid stocks with avg daily vol < ₹5 Cr. Check NSE."),
        ("SIP overlay",        "Deploy 50% now, 25% at next quarter, 25% after 6 months."),
        ("Stop-loss rule",     "If any stock drops >25% from entry, re-run screen & exit."),
        ("Paper trade first",  "Mirror this portfolio on paper for 1 quarter before going live."),
    ]
    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    t.add_column("Note", style="bold yellow", min_width=22)
    t.add_column("Detail")
    for k, v in notes:
        t.add_row(k, v)
    console.print(Panel(t, title="⚙️  Execution Notes", border_style="yellow"))
    console.print()


# ══════════════════════════════════════════════════════════════════════════════
# EXPORT
# ══════════════════════════════════════════════════════════════════════════════
def export_csv(port: pd.DataFrame, regime: dict, capital: float):
    ts   = datetime.now().strftime("%Y%m%d_%H%M")
    fname = f"nifty_portfolio_{ts}.csv"
    out  = port.copy()
    out["regime"]           = regime["state"]
    out["deploy_pct"]       = regime["deploy_pct"]
    out["effective_capital"]= capital * regime["deploy_pct"]
    out["run_date"]         = datetime.now().strftime("%Y-%m-%d")
    out.to_csv(fname)
    console.print(f"[green]✓[/green]  Portfolio exported → [bold]{fname}[/bold]")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════
def parse_args():
    p = argparse.ArgumentParser(description="Nifty 200 Multi-Factor Screener")
    p.add_argument("--capital",  type=float, default=200_000, help="Investible capital in INR (default: 200000)")
    p.add_argument("--top",      type=int,   default=10,      help="Number of stocks to select (default: 10)")
    p.add_argument("--factor",   type=str,   default="all",
                   choices=["all", "momentum", "quality", "value", "low_vol"],
                   help="Run a single-factor screen instead of composite")
    p.add_argument("--backtest", action="store_true", help="Run rolling backtest over available history")
    p.add_argument("--export",   action="store_true", help="Export portfolio to CSV")
    p.add_argument("--no-fundamentals", action="store_true",
                   help="Skip fundamental data fetch (faster, momentum only)")
    return p.parse_args()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    args = parse_args()
    print_header()

    # ── 1. Universe ──────────────────────────────────────────────────────────
    tickers = load_universe(Config.CSV_FILE)

    # ── 2. Price data ────────────────────────────────────────────────────────
    prices = fetch_prices(tickers, period="3y")

    # Drop stocks with insufficient history
    min_obs = Config.MIN_HISTORY
    prices  = prices.loc[:, prices.notna().sum() >= min_obs]
    console.print(f"[dim]{prices.shape[1]-1} stocks passed data quality filter[/dim]\n")

    # ── 3. Market Regime ─────────────────────────────────────────────────────
    index_prices = prices[Config.INDEX_TICKER].dropna()
    regime       = detect_regime(index_prices)
    print_regime(regime)
    print_factor_weights()

    # ── 4. Fundamentals ──────────────────────────────────────────────────────
    stock_tickers = [c for c in prices.columns if c != Config.INDEX_TICKER]
    if args.no_fundamentals or args.factor == "momentum":
        fundamentals = pd.DataFrame(index=stock_tickers)
    else:
        fundamentals = fetch_fundamentals(stock_tickers)

    # ── 5. Factor scores & composite ─────────────────────────────────────────
    console.print()
    scores = build_composite_score(prices, fundamentals, factor_mode=args.factor)

    # ── 6. Portfolio ─────────────────────────────────────────────────────────
    portfolio = construct_portfolio(
        scores, prices, fundamentals,
        capital=args.capital,
        top_n=args.top,
        regime=regime,
    )
    out_path = export_to_excel(
    portfolio=portfolio,
    regime=regime,
    capital=args.capital,
    factor_weights=Config.WEIGHTS,
    backtest=bt if args.backtest else None,
)

    

    print_portfolio(portfolio, args.capital, regime, args.top)
    print_rebalance_notes()

    # ── 7. Backtest (optional) ───────────────────────────────────────────────
    if args.backtest:
        bt = run_backtest(prices, fundamentals, top_n=args.top, capital=args.capital)
        print_backtest(bt)

    # ── 8. Export (optional) ─────────────────────────────────────────────────
    if args.export:
        export_csv(portfolio, regime, args.capital)

    console.rule("[dim]Run complete[/dim]")


if __name__ == "__main__":
    main()