# Nifty Multi-Factor Screener

A systematic long-only equity screener over the Nifty 200 universe, plus a web
UI to run it interactively. Replaces `rough-screener.py` (kept for reference)
with a proper backend service + frontend.

## What's new vs. the rough version

- **Growth factor** (revenue/earnings growth) split out from quality, so a
  profitable-but-stagnant stock doesn't get the same score as one that's
  actually growing.
- **Sector-relative scoring**: every fundamental factor blends a global
  z-score with a within-sector z-score, so one hot sector can't dominate
  every slot and "best of a weak sector" isn't over-rewarded either.
- **Liquidity gate**: stocks with average daily traded value below a
  threshold (default ₹5 Cr) are dropped before ranking — the old version had
  this as a comment in the execution notes but never enforced it.
- **Trend gate**: optional filter requiring price > 200-day SMA, so a
  statistically cheap stock in a structural downtrend doesn't get selected.
- **Diversified, correlation-aware selection**: greedy top-N selection that
  enforces a max-per-sector cap and skips candidates too highly correlated
  with an already-selected name, instead of just taking the top-N composite
  scores regardless of overlap.
- **Risk-based position sizing** (inverse volatility, clamped) plus a
  suggested ATR-based stop-loss level per position.
- **Missing-data handling**: fundamentals are median-filled per factor
  instead of silently dropping stocks with sparse data (previously biased
  against small/mid caps).
- **Backtest fix**: the original backtest re-invested only the
  regime-deployed *fraction of last quarter's invested value* each
  rebalance, silently discarding the cash buffer — compounding losses to
  near-zero whenever the regime stayed defensive for a few quarters. The
  fixed version tracks total equity (invested + cash) and carries the cash
  buffer forward correctly.
- **Disk-cached data layer**: yfinance price/fundamentals pulls are cached
  to parquet with a TTL, so the web UI serves screens instantly and only
  hits the network on an explicit refresh.

## Architecture

```
backend/   FastAPI service — data fetching/caching, factor engines,
           regime detection, portfolio construction, backtest
frontend/  React (Vite) single-page app
```

## Running it

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

First call `POST /api/refresh` (or click "Refresh Market Data" in the UI) to
pull price history + fundamentals for the Nifty 200 universe (~30-60s). After
that, screens and backtests run instantly off the cache.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. It talks to the backend at `http://127.0.0.1:8000`
by default — override with a `VITE_API_URL` env var if needed.

## API

- `GET  /api/status` — cache freshness / refresh progress
- `POST /api/refresh` — kick off a fresh network pull (async, poll `/api/status`)
- `GET  /api/regime` — current market regime only
- `POST /api/screen` — `{capital, top_n, weights, factor_mode, max_per_sector, min_liquidity_cr, require_uptrend}` → ranked portfolio
- `POST /api/backtest` — same params → rolling quarterly walk-forward backtest with equity curve

## Known limitations

- Fundamentals (P/E, ROE, growth, etc.) are point-in-time snapshots from
  yfinance, not point-in-time historical — the backtest treats them as
  static across the whole backtest window, which overstates the realism of
  the fundamentals-based factors (quality/growth/value) in the backtest.
  Momentum, low-vol, liquidity, and trend are computed correctly
  point-in-time since they only need price/volume history.
- Universe is Nifty 200 (`backend/data/universe.csv`) — swap that file
  (needs a `Symbol` column) to screen a different universe.
- This is a research/decision-support tool, not investment advice. Paper
  trade before committing capital.
