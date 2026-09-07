# Deploying

The code is pushed and CI is green. What remains needs your credentials, so
you do these bits yourself.

## 1. GitHub Actions secrets

Without these the nightly ingest and the backtest worker cannot run, and CI
skips the database-backed tests.

**Settings → Secrets and variables → Actions → New repository secret.**
Add four, copying each value from `backend/.env`:

| Secret | Where it comes from |
|---|---|
| `DATABASE_URL` | Neon connection string (the `-pooler` host) |
| `GROWW_API_KEY` | Groww trade-API key |
| `GROWW_SECRET` | Groww API secret |
| `INDIAN_API_KEY` | Indian Stock API key (`x-api-key`) |

Optionally add a repository **variable** (not a secret) `INDIAN_API_DAILY_BUDGET`,
default `400`. Raise it only for a one-off backfill.

If you install the GitHub CLI (`brew install gh && gh auth login`) you can do it
without the browser — run these yourself so the values never leave your machine
through anything but GitHub:

```bash
cd backend
gh secret set DATABASE_URL   --body "$(grep '^DATABASE_URL='   .env | cut -d= -f2-)"
gh secret set GROWW_API_KEY  --body "$(grep '^GROWW_API_KEY='  .env | cut -d= -f2-)"
gh secret set GROWW_SECRET   --body "$(grep '^GROWW_SECRET='   .env | cut -d= -f2- | tr -d '\"')"
gh secret set INDIAN_API_KEY --body "$(grep '^INDIAN_API_KEY=' .env | cut -d= -f2-)"
```

Then confirm the pipeline end to end: **Actions → Nightly ingest → Run workflow**.
It should finish in 10–20 minutes and the Data health page will show the run.

> One caveat: CI runs the test suite against whatever `DATABASE_URL` you set.
> The tests roll back everything they do, but they share the database with your
> live data. If that makes you uneasy, create a second free Neon branch and
> point the CI secret at that instead.

## 2. Render

**New → Blueprint**, point it at `TejasBaid/stockpicker`. Render reads
`render.yaml` and creates two services.

On **screener-api** set:

| Variable | Value |
|---|---|
| `DATABASE_URL` | same Neon string |
| `GROWW_API_KEY`, `GROWW_SECRET`, `INDIAN_API_KEY` | same as above |
| `CORS_ORIGINS` | the static site's URL, e.g. `https://screener-web.onrender.com` |

`SECRET_KEY` is generated for you; `ENVIRONMENT`, `COOKIE_SECURE` and
`PYTHON_VERSION` are already set in the blueprint.

On **screener-web** set `VITE_API_URL` to the API's URL, e.g.
`https://screener-api.onrender.com`. Redeploy the static site after setting it —
Vite bakes the value in at build time.

Migrations apply themselves: the start command runs `alembic upgrade head`
before uvicorn.

## 3. Keep-warm pinger

Render's free tier sleeps after 15 minutes idle and takes ~50s to wake. Point a
free pinger (cron-job.org, UptimeRobot) at `https://<api>/health` every 10
minutes, **weekdays 09:00–16:00 IST only** — roughly 154 of the 750 free
instance-hours a month, so it is awake when you use it and asleep otherwise.

## Notes

* Scheduled workflows are disabled after 60 days of repository inactivity, and
  scheduled runs can be delayed 10–15 minutes at peak. Neither matters for a
  nightly ingest.
* The ingest is a standalone CLI (`python -m app.ingest.jobs nightly`), so
  moving it to a paid Render cron job later is a config change, not a rewrite.
* Render installs from `backend/requirements.txt`, exported from `uv.lock`. CI
  fails if the two drift, so regenerate with
  `uv export --no-dev --no-hashes --no-emit-project -o requirements.txt` after
  changing dependencies.
