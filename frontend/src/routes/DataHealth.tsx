import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, RefreshCw, XCircle } from 'lucide-react'
import { PageHeader } from '@/components/layout/AppShell'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Spinner } from '@/components/ui/spinner'
import { Meter, Stat } from '@/components/ui/stat'
import { dataApi, type IngestRun } from '@/lib/api'

export default function DataHealth() {
  const { data, isPending, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['data', 'overview'],
    queryFn: dataApi.overview,
    refetchInterval: 60_000,
  })

  if (isPending) {
    return (
      <>
        <PageHeader title="Data health" />
        <div className="text-muted flex items-center gap-2 p-6 text-sm">
          <Spinner /> Loading…
        </div>
      </>
    )
  }

  if (isError) {
    return (
      <>
        <PageHeader title="Data health" />
        <div className="p-6">
          <Alert tone="error">{(error as Error).message}</Alert>
        </div>
      </>
    )
  }

  const stale = data.bars_stale_days
  const pit = data.point_in_time
  const quota = data.provider_usage.indian_api

  return (
    <>
      <PageHeader
        title="Data health"
        description="Freshness, coverage, point-in-time quality and API budget."
        action={
          <button
            onClick={() => refetch()}
            className="text-muted hover:text-[var(--text)] flex items-center gap-1.5 text-sm"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        }
      />

      <div className="space-y-6 p-6">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Universe" value={data.universe_size} hint="Nifty 200 constituents" />
          <Stat
            label="Latest price bar"
            value={data.latest_bar_date ?? '—'}
            hint={stale == null ? undefined : stale <= 4 ? `${stale}d ago` : `${stale} days stale`}
            tone={stale == null ? 'default' : stale <= 4 ? 'default' : 'warning'}
          />
          <Stat
            label="Point-in-time exact"
            value={`${pit.exact_pct}%`}
            hint={`${pit.exact_rows.toLocaleString()} of ${pit.total_rows.toLocaleString()} statement rows`}
            tone={pit.exact_pct >= 60 ? 'positive' : 'warning'}
          />
          <Stat
            label="API calls today"
            value={quota.used_today.toLocaleString()}
            hint={`of ${quota.daily_budget.toLocaleString()} budget`}
            tone={quota.pct_used > 85 ? 'negative' : 'default'}
          />
        </div>

        <Card>
          <CardHeader
            title="Point-in-time dating"
            description="Rows dated by an actual earnings announcement, versus the statutory filing deadline."
          />
          <CardBody className="space-y-3">
            <Meter pct={pit.exact_pct} tone={pit.exact_pct >= 60 ? 'accent' : 'warn'} />
            <p className="text-muted text-xs leading-relaxed">
              {pit.exact_rows.toLocaleString()} rows carry the real announcement date from the
              analyst-estimate feed. The remaining {pit.estimated_rows.toLocaleString()} fall back
              to the SEBI filing deadline — 45 days after a quarter, 60 after a year end. The
              fallback is deliberately late, so a backtest understates rather than invents an edge.
            </p>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Datasets" description="Coverage across the Nifty 200." />
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-muted border-b text-xs">
                <tr>
                  <th className="px-5 py-2.5 text-left font-medium">Dataset</th>
                  <th className="px-5 py-2.5 text-left font-medium">Source</th>
                  <th className="px-5 py-2.5 text-right font-medium">Symbols</th>
                  <th className="px-5 py-2.5 text-right font-medium">Rows</th>
                  <th className="px-5 py-2.5 text-left font-medium">Coverage</th>
                </tr>
              </thead>
              <tbody>
                {data.datasets.map((d) => (
                  <tr key={d.key} className="border-b last:border-0">
                    <td className="px-5 py-3">
                      <div className="font-medium">{d.label}</div>
                      {d.note ? <div className="text-muted text-xs">{d.note}</div> : null}
                    </td>
                    <td className="text-muted px-5 py-3 text-xs">{d.source}</td>
                    <td className="tabular px-5 py-3 text-right">{d.symbols}</td>
                    <td className="tabular px-5 py-3 text-right">{d.rows.toLocaleString()}</td>
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-2">
                        <Meter
                          pct={d.coverage_pct}
                          tone={d.coverage_pct >= 90 ? 'accent' : d.coverage_pct >= 40 ? 'warn' : 'neg'}
                        />
                        <span className="tabular text-muted w-12 text-right text-xs">
                          {d.coverage_pct}%
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Recent ingest runs"
            description="The nightly pipeline runs on GitHub Actions, not on this server."
          />
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-muted border-b text-xs">
                <tr>
                  <th className="px-5 py-2.5 text-left font-medium">Job</th>
                  <th className="px-5 py-2.5 text-left font-medium">Started</th>
                  <th className="px-5 py-2.5 text-right font-medium">Duration</th>
                  <th className="px-5 py-2.5 text-right font-medium">Rows</th>
                  <th className="px-5 py-2.5 text-right font-medium">Symbols</th>
                  <th className="px-5 py-2.5 text-left font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_runs.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="text-muted px-5 py-8 text-center text-sm">
                      No ingest runs yet.
                    </td>
                  </tr>
                ) : (
                  data.recent_runs.map((r) => <RunRow key={r.id} run={r} />)
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  )
}

function RunRow({ run }: { run: IngestRun }) {
  const Icon = run.status === 'ok' ? CheckCircle2 : run.status === 'running' ? RefreshCw : XCircle
  const tone = run.status === 'ok' ? 'ok' : run.status === 'running' ? 'muted' : 'fail'
  return (
    <tr className="border-b last:border-0">
      <td className="px-5 py-2.5 font-medium">{run.job}</td>
      <td className="text-muted tabular px-5 py-2.5 text-xs">
        {new Date(run.started_at).toLocaleString('en-IN', {
          dateStyle: 'medium',
          timeStyle: 'short',
        })}
      </td>
      <td className="tabular px-5 py-2.5 text-right text-xs">
        {run.duration_seconds != null ? `${run.duration_seconds.toFixed(1)}s` : '—'}
      </td>
      <td className="tabular px-5 py-2.5 text-right">{run.rows_written.toLocaleString()}</td>
      <td className="tabular px-5 py-2.5 text-right">
        {run.symbols_processed}
        {run.symbols_failed > 0 ? (
          <span className="text-neg"> ({run.symbols_failed} failed)</span>
        ) : null}
      </td>
      <td className="px-5 py-2.5">
        <Badge tone={tone}>
          <Icon className="mr-1 h-3 w-3" />
          {run.status}
        </Badge>
        {run.error ? (
          <div className="text-neg mt-1 flex items-start gap-1 text-xs">
            <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
            <span className="line-clamp-2">{run.error}</span>
          </div>
        ) : null}
      </td>
    </tr>
  )
}
