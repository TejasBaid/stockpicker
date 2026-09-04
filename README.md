# Nifty 200 Investment Platform

A multi-factor screening and portfolio-planning platform for Indian equities:
deep fundamentals, custom strategies, point-in-time backtests, and long-term
position tracking with planned exits.

## Status

**Feature complete.** The Nifty 200 is loaded, screenable across 48 factors,
backtestable point-in-time with Indian transaction costs, and trackable as a
portfolio with exit plans and tax treatment.

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

## Backtesting

Walk-forward and strictly point-in-time: at every rebalance date the engine
rebuilds the panel *as of that date* and recomputes the strategy's factors from
it. It never reuses the precomputed factor table, because that table describes
today.

Historical fundamentals are reconstructed from the statements rather than the
vendor's precomputed metrics — those are a single snapshot of today with no
history. Market capitalisation comes from the price on the date and the share
count then reported, trailing-twelve-month profit from the four quarters known
by then, and so on. Nothing uses a figure the market could not have seen, and
`tests/test_backtest.py` asserts it rather than assuming it.

**On benchmarks.** Results are reported against the equal-weighted Nifty 200 as
well as the Nifty 50, and the equal-weighted line is the one that matters. The
Nifty 50 is large-cap only, so *any* Nifty 200 strategy beats it whenever mid
caps lead — a null strategy holding 150 of the 200 names returned 15.6% a year
against the index's 6.8% while containing no skill whatsoever. Measured against
the Nifty 50, the quality-value preset shows +14.6pp of "alpha"; measured
against equal-weighting the same universe, it shows **−0.8pp**. The platform
reports the honest number.

Costs are modelled per component — STT, stamp duty (buy side only), exchange
and SEBI charges, GST on brokerage, and slippage — because turnover matters: a
quarterly strategy spends 2–4% of capital a year, and a momentum strategy 8%.

Backtests run as queued jobs on a GitHub Actions worker, not in the web
process:

```bash
uv run python -m app.backtest.worker --max-jobs 5
```

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

## Portfolio

Positions are entered by hand — this platform never reads your brokerage
account. Valuation uses the latest stored daily close rather than a live quote,
so the request path makes no external call and works whether or not the market
is open.

* **Exit plans defined at entry, not in a panic.** ATR-based stops (resolved to
  a price at planning time, so they are a commitment rather than a moving
  target), target ladders, and time stops.
* **Factor-decay exits.** The factor deciles behind the thesis are snapshotted
  when a position opens, so the platform can tell you that the quality rank you
  bought on has fallen from decile 2 to decile 8 — a reasoned exit rather than a
  reaction to price.
* **Indian tax treatment.** First-in-first-out lot matching as brokers report
  it, the twelve-month long-term boundary, the ₹1.25 lakh LTCG exemption, and a
  countdown of days until a holding qualifies. Estimates only, not tax advice.

## Deploying

1. **Neon** — already provisioned. `alembic upgrade head` runs on every Render
   boot, so migrations apply themselves.
2. **GitHub secrets** (Settings → Secrets and variables → Actions): add
   `DATABASE_URL`, `GROWW_API_KEY`, `GROWW_SECRET`, `INDIAN_API_KEY`. Optionally
   set the `INDIAN_API_DAILY_BUDGET` repository *variable*. Without these the
   nightly ingest and the backtest worker cannot run.
3. **Render** — deploy `render.yaml` as a blueprint. Set `DATABASE_URL`,
   the two Groww secrets, `INDIAN_API_KEY`, and `CORS_ORIGINS` (the static
   site's URL) on the API service, and `VITE_API_URL` (the API's URL) on the
   static site.
4. **Keep-warm pinger** — point a free service (cron-job.org, UptimeRobot) at
   `https://<api>/health` every 10 minutes, weekdays 09:00–16:00 IST only. That
   is roughly 154 of the 750 free instance-hours a month, so the API is awake
   when you use it and asleep the rest of the time.
5. **First account** — `python -m app.cli invite` to mint a code. The first
   account created becomes the administrator.

GitHub disables scheduled workflows after 60 days of repository inactivity, and
scheduled runs can be delayed 10–15 minutes at peak. Neither matters for a
nightly ingest; if it ever does, the ingest is a standalone CLI, so promoting it
to a paid Render cron job is a config change rather than a rewrite.

## Not investment advice

This is a research tool. It does not place orders and it does not tell you what
to buy.
