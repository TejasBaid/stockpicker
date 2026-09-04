import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { PageHeader } from '@/components/layout/AppShell'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { Stat } from '@/components/ui/stat'
import { backtestApi, screenerApi, type BacktestJob, type BacktestResult } from '@/lib/api'
import { formatInr } from '@/lib/utils'

export default function Backtests() {
  const qc = useQueryClient()
  const { data: presetData } = useQuery({
    queryKey: ['screener', 'presets'],
    queryFn: screenerApi.presets,
    staleTime: Infinity,
  })

  const [preset, setPreset] = useState('quality_value')
  const [start, setStart] = useState('2022-01-03')
  const [end, setEnd] = useState('2026-08-29')
  const [holdings, setHoldings] = useState(20)
  const [frequency, setFrequency] = useState('quarterly')
  const [activeId, setActiveId] = useState<string | null>(null)

  const { data: jobs } = useQuery({
    queryKey: ['backtests'],
    queryFn: backtestApi.list,
    refetchInterval: 15_000,
  })

  const { data: job } = useQuery({
    queryKey: ['backtest', activeId],
    queryFn: () => backtestApi.get(activeId as string),
    enabled: !!activeId,
    // Poll while the worker is picking the job up; results are written back.
    refetchInterval: (q) => {
      const s = (q.state.data as BacktestJob | undefined)?.status
      return s === 'queued' || s === 'running' ? 5_000 : false
    },
  })

  const enqueue = useMutation({
    mutationFn: backtestApi.enqueue,
    onSuccess: (j) => {
      setActiveId(j.id)
      qc.invalidateQueries({ queryKey: ['backtests'] })
    },
  })

  function run() {
    const p = presetData?.presets.find((x) => x.slug === preset)
    if (!p) return
    enqueue.mutate({
      weights: p.weights,
      filters: p.filters,
      start,
      end,
      holdings,
      frequency,
      max_per_sector: 4,
    })
  }

  return (
    <>
      <PageHeader
        title="Backtests"
        description="Point-in-time walk-forward, with Indian transaction costs. Nothing sees a result before it was announced."
      />

      <div className="space-y-5 p-6">
        <Card>
          <CardHeader title="Run a backtest" />
          <CardBody>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
              <Field label="Strategy" htmlFor="preset">
                <select
                  id="preset"
                  value={preset}
                  onChange={(e) => setPreset(e.target.value)}
                  className="surface h-9 w-full rounded-md border px-3 text-sm"
                >
                  {presetData?.presets.map((p) => (
                    <option key={p.slug} value={p.slug}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="From" htmlFor="start">
                <Input id="start" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
              </Field>
              <Field label="To" htmlFor="end">
                <Input id="end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
              </Field>
              <Field label="Holdings" htmlFor="holdings">
                <Input
                  id="holdings"
                  type="number"
                  min={3}
                  max={100}
                  value={holdings}
                  onChange={(e) => setHoldings(Number(e.target.value))}
                />
              </Field>
              <Field label="Rebalance" htmlFor="freq">
                <select
                  id="freq"
                  value={frequency}
                  onChange={(e) => setFrequency(e.target.value)}
                  className="surface h-9 w-full rounded-md border px-3 text-sm"
                >
                  <option value="monthly">Monthly</option>
                  <option value="quarterly">Quarterly</option>
                  <option value="yearly">Yearly</option>
                </select>
              </Field>
            </div>
            <div className="mt-4 flex items-center gap-3">
              <Button onClick={run} disabled={enqueue.isPending}>
                {enqueue.isPending ? <Spinner /> : null}
                Queue backtest
              </Button>
              <p className="text-muted text-xs">
                Runs on a GitHub Actions worker, not this server — results usually land within a
                few minutes.
              </p>
            </div>
            {enqueue.isError ? (
              <Alert tone="error" className="mt-3">
                {(enqueue.error as Error).message}
              </Alert>
            ) : null}
          </CardBody>
        </Card>

        {job ? <JobPanel job={job} /> : null}

        {jobs?.length ? (
          <Card>
            <CardHeader title="Recent backtests" />
            <div className="divide-y">
              {jobs.map((j) => (
                <button
                  key={j.id}
                  onClick={() => setActiveId(j.id)}
                  className="hover:surface-2 flex w-full items-center justify-between px-5 py-3 text-left text-sm"
                >
                  <span className="text-muted">
                    {new Date(j.created_at).toLocaleString('en-IN', {
                      dateStyle: 'medium',
                      timeStyle: 'short',
                    })}
                  </span>
                  <Badge tone={j.status === 'done' ? 'ok' : j.status === 'failed' ? 'fail' : 'muted'}>
                    {j.status}
                  </Badge>
                </button>
              ))}
            </div>
          </Card>
        ) : null}
      </div>
    </>
  )
}

function JobPanel({ job }: { job: BacktestJob }) {
  if (job.status === 'queued' || job.status === 'running') {
    return (
      <Card>
        <CardBody className="text-muted flex items-center gap-3 text-sm">
          <Spinner />
          <div>
            <p className="text-[var(--text)]">
              {job.status === 'queued' ? 'Queued' : 'Running'}…
            </p>
            <p className="text-xs">
              The worker polls every ten minutes, or you can trigger the “Backtest worker”
              workflow manually in GitHub Actions to pick it up now.
            </p>
          </div>
        </CardBody>
      </Card>
    )
  }
  if (job.status === 'failed') {
    return <Alert tone="error">{job.error ?? 'The backtest failed.'}</Alert>
  }
  if (!job.result) return null
  return <Results result={job.result} />
}

function Results({ result }: { result: BacktestResult }) {
  const m = result.metrics
  const merged = mergeCurves(result)
  const realAlpha = m.alpha_vs_universe_pct

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Final value"
          value={formatInr(result.final_value, { compact: true })}
          hint={`from ${formatInr(result.initial_capital, { compact: true })}`}
        />
        <Stat
          label="CAGR"
          value={`${m.cagr_pct}%`}
          hint={`${m.total_return_pct}% total`}
          tone={m.cagr_pct > 0 ? 'positive' : 'negative'}
        />
        <Stat
          label="Sharpe"
          value={m.sharpe ?? '—'}
          hint={`Sortino ${m.sortino ?? '—'} · vol ${m.volatility_pct}%`}
        />
        <Stat
          label="Max drawdown"
          value={`${m.max_drawdown_pct}%`}
          hint={`index ${m.benchmark_max_drawdown_pct ?? '—'}%`}
          tone="warning"
        />
      </div>

      {realAlpha != null ? (
        <Alert tone={realAlpha > 1 ? 'success' : 'info'}>
          <div className="space-y-1">
            <p className="font-medium">
              Alpha versus the equal-weighted Nifty 200: {realAlpha > 0 ? '+' : ''}
              {realAlpha}pp a year
            </p>
            <p className="text-xs leading-relaxed">
              Against the Nifty 50 this strategy shows {m.alpha_pct}pp, but the Nifty 50 is
              large-cap only — simply owning all 200 names equally returned{' '}
              {m.universe_cagr_pct}% a year over this period. The number above is what the
              strategy's <em>selection</em> actually added, and it is the one worth trusting.
            </p>
          </div>
        </Alert>
      ) : null}

      <Card>
        <CardHeader
          title="Equity curve"
          description="Strategy against the equal-weighted universe and the Nifty 50."
        />
        <CardBody>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={merged} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="date"
                  tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                  minTickGap={60}
                  stroke="var(--border)"
                />
                <YAxis
                  tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                  tickFormatter={(v) => `${(v / 100000).toFixed(1)}L`}
                  stroke="var(--border)"
                  width={48}
                />
                <Tooltip
                  contentStyle={{
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  formatter={(v) => formatInr(typeof v === 'number' ? v : null, { compact: true })}
                />
                <Line
                  type="monotone"
                  dataKey="strategy"
                  stroke="var(--accent)"
                  strokeWidth={2}
                  dot={false}
                  name="Strategy"
                />
                <Line
                  type="monotone"
                  dataKey="universe"
                  stroke="var(--warn)"
                  strokeWidth={1.5}
                  dot={false}
                  name="Equal-weight Nifty 200"
                />
                <Line
                  type="monotone"
                  dataKey="nifty"
                  stroke="var(--text-muted)"
                  strokeWidth={1.5}
                  strokeDasharray="4 4"
                  dot={false}
                  name="Nifty 50"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="text-muted mt-3 flex flex-wrap gap-4 text-xs">
            <Legend color="var(--accent)" label={`Strategy ${m.cagr_pct}%`} />
            <Legend color="var(--warn)" label={`Equal-weight Nifty 200 ${m.universe_cagr_pct}%`} />
            <Legend color="var(--text-muted)" label={`Nifty 50 ${m.benchmark_cagr_pct}%`} dashed />
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Trading" description="What the strategy cost to run." />
        <CardBody className="grid gap-4 sm:grid-cols-4">
          <Metric label="Rebalances" value={m.rebalances} />
          <Metric label="Trades" value={m.trades} />
          <Metric label="Total costs" value={formatInr(m.total_costs, { compact: true })} />
          <Metric label="Cost drag" value={`${m.cost_drag_pct}% of capital`} />
        </CardBody>
      </Card>
    </div>
  )
}

function Legend({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className="inline-block h-0.5 w-4"
        style={{
          background: dashed
            ? `repeating-linear-gradient(90deg, ${color} 0 4px, transparent 4px 8px)`
            : color,
        }}
      />
      {label}
    </span>
  )
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-muted text-xs">{label}</p>
      <p className="tabular mt-0.5 text-lg font-semibold">{value}</p>
    </div>
  )
}

function mergeCurves(result: BacktestResult) {
  const byDate = new Map<string, { date: string; strategy?: number; nifty?: number; universe?: number }>()
  for (const p of result.equity_curve) byDate.set(p.date, { date: p.date, strategy: p.value })
  for (const p of result.benchmark_curve) {
    const row = byDate.get(p.date) ?? { date: p.date }
    row.nifty = p.value
    byDate.set(p.date, row)
  }
  for (const p of result.universe_curve) {
    const row = byDate.get(p.date) ?? { date: p.date }
    row.universe = p.value
    byDate.set(p.date, row)
  }
  return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date))
}
