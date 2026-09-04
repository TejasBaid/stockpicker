# Nifty 200 Investment Platform

A multi-factor screening and portfolio-planning platform for Indian equities:
deep fundamentals, custom strategies, point-in-time backtests, and long-term
position tracking with planned exits.

## Status

**Phase 2 — factors and screener.** The Nifty 200 is loaded and screenable
across 48 factors. Strategy building, backtests and portfolio tracking arrive
in phases 3–4.

## Data sources

| Source | Used for | Not used for |
|---|---|---|
| [Indian Stock API](https://stock.indianapi.in) | ~145 fundamental metrics per stock, 8 annual + 11 interim periods of income statement / balance sheet / cash flow, analyst estimates and revisions, price targets, shareholding, corporate actions, announcements, valuation-multiple history | — |
| [Groww Trade API](https://groww.in/trade-api/docs/python-sdk) | Instrument master, daily OHLCV candles, live quotes | **Holdings, positions, orders and margin are never called.** No endpoint that touches the brokerage account exists in this codebase. |

Both providers key off the plain NSE trading symbol (`TATASTEEL`), which is the
join key throughout. Two vendor quirks are handled automatically:

* The Indian API cannot resolve symbols containing `&` (`M&M`, `GVT&D`) even
  URL-encoded. Aliases are discovered via `/industry_search` and cached in
  `instruments.vendor_lookup_name` rather than hardcoded.
* Groww's current `get_historical_candles` returns a null `open` for every daily
  equity candle and caps a request at 180 days. The deprecated
  `get_historical_candle_data` returns complete OHLCV over 1080 days, so daily
  bars use it, falling back to the current endpoint if it is withdrawn.

### Point-in-time correctness

Every fundamental row stores `known_on` — the date the market could first have
known it. Screens and backtests filter on it.

The vendor's `StatementDate` field is broken (it reports the same date for every
fiscal period), so `known_on` comes from `/stock_forecasts.ActualReportDate`
where available, and otherwise from the SEBI LODR Reg. 33 filing deadline
(fiscal end + 45 days interim, + 60 days annual). Rows using the fallback are
flagged `known_on_estimated` and surfaced in the UI, so a backtest never quietly
overstates its edge.

## Architecture

```
GitHub Actions (scheduler + compute)
  ├─ nightly: ingest bars, fundamentals, statements, estimates, actions
  ├─ nightly: precompute all factor values, z-scores, sector ranks, deciles
  └─ on demand: run queued backtest jobs
                  │
                  ▼
          Neon Postgres  ◀── the only state
                  │
                  ▼
  Render free web service (FastAPI)  →  reads SQL, serves JSON
  Render static site (React + TS)    →  free, never sleeps
```

Render's free tier has no cron jobs, no background workers and no persistent
disk, and gives 512 MB / ~0.1 CPU. So all heavy work happens in GitHub Actions,
factors are precomputed rather than calculated per request, and the web service
only reads. See `render.yaml` and `.github/workflows/`.

## Local development

Requires Python 3.13 ([uv](https://docs.astral.sh/uv/)), Node 22+, and a Neon
Postgres database.

```bash
cp backend/.env.example backend/.env    # then fill in the values

cd backend
uv sync
uv run alembic upgrade head
uv run python -m app.cli invite --label "you"   # mint your first invite code
uv run uvicorn app.main:app --reload

cd ../frontend
npm install
npm run dev                              # http://localhost:5173
```

Access is invite-only; there is no public sign-up. The first account created
becomes the administrator.

### Checks

```bash
cd backend  && uv run ruff check app tests && uv run mypy app && uv run pytest
cd frontend && npx tsc -b --noEmit && npm run build
```

Tests run against real Postgres inside a rolled-back transaction. Note that
Neon's pooled (`-pooler`) endpoint is PgBouncer in transaction mode: session
state leaks between clients, so no code here may issue a session-level `SET` —
`search_path` is pinned by a role default instead.

## Factors

48 factors across seven families — value, quality, growth, momentum, revisions,
risk and ownership — each a pure function of a point-in-time panel, registered
with the metadata the UI reads directly.

They are **precomputed nightly**, never in the request path: the web service has
512 MB and roughly a tenth of a CPU, so a screen has to be an indexed read plus
a weighted sum, not a pandas job over six years of bars.

Each factor is winsorized, z-scored globally and (where the factor is
sector-bound) within sector, sign-flipped so every stored score reads
higher-is-better, then stored with its percentile, decile and coverage. Names
missing a factor score neutrally on it rather than being dropped — dropping
them would quietly bias every screen toward large caps with fuller coverage.

Two things worth knowing about the data:

* The vendor reports market capitalisation in rupee **crore** but every absolute
  statement figure in rupee **million**. Any factor mixing the two is wrong by a
  factor of ten; `CRORE_TO_MILLION` in `app/factors/value.py` marks where that
  conversion happens.
* Factors built on balance-sheet structure — net cash, interest coverage — are
  masked for lenders, whose borrowings are their raw material rather than
  leverage. They are not merely extreme there, they are meaningless.

## Ingest

```bash
uv run python -m app.ingest.jobs nightly          # everything, staggered
uv run python -m app.ingest.jobs instruments      # master list + Nifty 200 seed
uv run python -m app.ingest.jobs bars             # daily OHLCV (Groww)
uv run python -m app.ingest.jobs estimates --full # analyst estimates + targets
uv run python -m app.ingest.jobs fundamentals --full
uv run python -m app.ingest.jobs bars --symbols RELIANCE,TATASTEEL
```

Expensive jobs are **staggered**: each nightly run refreshes one slice of the
universe, cycling through it over a week rather than spending a week's API
budget in one night. `--full` overrides that, and an explicit `--symbols` list
implies it.

The Indian API publishes no quota headers, so every call is counted in
`provider_calls_daily` and checked against `INDIAN_API_DAILY_BUDGET` before it
is made. Exhausting the budget raises rather than silently truncating a run.

## Admin CLI

```bash
uv run python -m app.cli invite --label "name" --ttl-days 14
uv run python -m app.cli whoami
uv run python -m app.cli delete-user EMAIL
uv run python -m app.cli purge-sessions
```

## Not investment advice

This is a research tool. It does not place orders and it does not tell you what
to buy.
