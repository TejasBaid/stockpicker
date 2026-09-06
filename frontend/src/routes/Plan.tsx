import { useMutation, useQuery } from '@tanstack/react-query'
import { CalendarClock, Gauge, RefreshCw, Repeat, TriangleAlert, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { PageHeader } from '@/components/layout/AppShell'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { Meter, Stat } from '@/components/ui/stat'
import { planApi, screenerApi, strategyApi, type Allocation, type InvestmentPlan } from '@/lib/api'
import { cn, formatInr, formatNumber } from '@/lib/utils'

const SIZINGS = [
  { value: 'equal', label: 'Equal weight', hint: 'Same rupee amount in each. Hard to beat.' },
  { value: 'inverse_vol', label: 'Inverse volatility', hint: 'Less in the jumpy names.' },
  { value: 'equal_risk', label: 'Equal risk', hint: 'Same loss in each if every stop is hit.' },
  { value: 'conviction', label: 'Conviction', hint: 'More in the higher-ranked names.' },
]

export default function Plan() {
  const [capital, setCapital] = useState('500000')
  const [strategy, setStrategy] = useState('quality_value')
  const [holdings, setHoldings] = useState(15)
  const [sizing, setSizing] = useState('equal')
  // Sector limits are available but off by default: concentration is worth a
  // glance, not a constraint that overrides what the strategy actually ranked.
  const [maxPerSector, setMaxPerSector] = useState<number | null>(null)
  const [excluded, setExcluded] = useState<string[]>([])
  const [overrideDeploy, setOverrideDeploy] = useState<number | null>(null)

  const { data: presets } = useQuery({
    queryKey: ['screener', 'presets'],
    queryFn: screenerApi.presets,
    staleTime: Infinity,
  })
  const { data: saved } = useQuery({ queryKey: ['strategies'], queryFn: strategyApi.list })

  const plan = useMutation({ mutationFn: planApi.create })

  const amount = Number(capital.replace(/[^0-9.]/g, '')) || 0

  useEffect(() => {
    if (amount > 0) {
      plan.mutate({
        capital: amount,
        strategy,
        holdings,
        sizing,
        max_per_sector: maxPerSector,
        excluded,
        override_deploy_pct: overrideDeploy,
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [amount, strategy, holdings, sizing, maxPerSector, excluded, overrideDeploy])

  const result = plan.data

  return (
    <>
      <PageHeader
        title="Plan an investment"
        description="Enter an amount. The market decides how much to deploy; the strategy decides where."
      />

      <div className="space-y-4 px-7 pb-8">
        <Card>
          <CardBody className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <Field label="Amount to invest" htmlFor="capital">
              <Input
                id="capital"
                inputMode="numeric"
                value={capital}
                onChange={(e) => setCapital(e.target.value)}
                className="tabular font-medium"
              />
            </Field>
            <Field label="Strategy" htmlFor="strategy">
              <select
                id="strategy"
                value={strategy}
                onChange={(e) => setStrategy(e.target.value)}
                className="surface h-9 w-full rounded-md border px-3 text-sm"
              >
                {saved?.length ? (
                  <optgroup label="Yours">
                    {saved.map((s) => (
                      <option key={s.id} value={s.slug}>
                        {s.name}
                      </option>
                    ))}
                  </optgroup>
                ) : null}
                <optgroup label="Presets">
                  {presets?.presets.map((p) => (
                    <option key={p.slug} value={p.slug}>
                      {p.name}
                    </option>
                  ))}
                </optgroup>
              </select>
            </Field>
            <Field label="Holdings" htmlFor="holdings">
              <Input
                id="holdings"
                type="number"
                min={3}
                max={50}
                value={holdings}
                onChange={(e) => setHoldings(Number(e.target.value))}
              />
            </Field>
            <Field
              label="Sizing"
              htmlFor="sizing"
              hint={SIZINGS.find((s) => s.value === sizing)?.hint}
            >
              <select
                id="sizing"
                value={sizing}
                onChange={(e) => setSizing(e.target.value)}
                className="surface h-9 w-full rounded-md border px-3 text-sm"
              >
                {SIZINGS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Max per sector" htmlFor="mps">
              <select
                id="mps"
                value={maxPerSector ?? ''}
                onChange={(e) =>
                  setMaxPerSector(e.target.value === '' ? null : Number(e.target.value))
                }
                className="surface h-9 w-full rounded-md border px-3 text-sm"
              >
                <option value="">No limit</option>
                {[2, 3, 4, 5, 8].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </Field>
          </CardBody>
        </Card>

        {plan.isError ? <Alert tone="error">{(plan.error as Error).message}</Alert> : null}
        {plan.isPending && !result ? (
          <div className="text-muted flex items-center gap-2 text-sm">
            <Spinner /> Working out a plan…
          </div>
        ) : null}

        {result ? (
          <>
            <RegimePanel
              plan={result}
              override={overrideDeploy}
              onOverride={setOverrideDeploy}
            />
            <Summary plan={result} />
            <Allocations
              plan={result}
              onSwap={(symbol) => setExcluded((e) => [...e, symbol])}
            />
            {excluded.length ? (
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-muted">Swapped out:</span>
                {excluded.map((s) => (
                  <button
                    key={s}
                    onClick={() => setExcluded((e) => e.filter((x) => x !== s))}
                    className="surface-2 flex items-center gap-1 rounded-full border px-2 py-0.5 hover:border-[var(--accent)]"
                  >
                    {s} <X className="h-3 w-3" />
                  </button>
                ))}
                <button
                  onClick={() => setExcluded([])}
                  className="text-[var(--accent)] hover:underline"
                >
                  reset
                </button>
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </>
  )
}

function RegimePanel({
  plan,
  override,
  onOverride,
}: {
  plan: InvestmentPlan
  override: number | null
  onOverride: (v: number | null) => void
}) {
  const r = plan.regime
  const tone =
    r.state === 'risk_on' ? 'ok' : r.state === 'risk_off' ? 'fail' : 'warn'
  const label =
    r.state === 'risk_on' ? 'Constructive' : r.state === 'risk_off' ? 'Hostile' : 'Mixed'

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Gauge className="h-4 w-4" />
            Market conditions
            <Badge tone={tone}>{label}</Badge>
          </span>
        }
        description={`Nifty as of ${r.as_of}`}
      />
      <CardBody className="space-y-4">
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-3">
            {r.signals.map((s) => (
              <div key={s.key}>
                <div className="mb-1 flex items-baseline justify-between text-sm">
                  <span>{s.label}</span>
                  <span className="tabular text-muted text-xs">{s.score.toFixed(2)}</span>
                </div>
                <Meter
                  pct={s.score * 100}
                  tone={s.score >= 0.6 ? 'accent' : s.score >= 0.35 ? 'warn' : 'neg'}
                />
                <p className="text-muted mt-1 text-xs">{s.detail}</p>
              </div>
            ))}
          </div>

          <div className="space-y-3">
            <div className="surface-2 rounded-lg border p-4">
              <p className="text-muted text-xs">Suggested deployment</p>
              <p className="tabular mt-1 text-3xl font-semibold">{plan.deploy_pct}%</p>
              <p className="text-muted mt-1 text-xs">{r.note}</p>
              <div className="mt-3">
                <label htmlFor="deploy" className="text-muted mb-1 block text-xs">
                  Override
                </label>
                <div className="flex items-center gap-2">
                  <input
                    id="deploy"
                    type="range"
                    min={0}
                    max={100}
                    step={5}
                    value={override ?? r.suggested_deploy_pct}
                    onChange={(e) => onOverride(Number(e.target.value))}
                    className="flex-1 accent-[var(--accent)]"
                  />
                  {override !== null ? (
                    <button
                      onClick={() => onOverride(null)}
                      className="text-muted hover:text-[var(--accent)] text-xs"
                      title="Back to the suggestion"
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                    </button>
                  ) : null}
                </div>
              </div>
            </div>

            <div>
              <p className="text-muted mb-2 flex items-center gap-1.5 text-xs">
                <CalendarClock className="h-3.5 w-3.5" />
                Stage the entry
              </p>
              <div className="space-y-1.5">
                {plan.tranches.map((t, i) => (
                  <div key={i} className="flex items-center justify-between text-sm">
                    <span className="text-muted">{t.label}</span>
                    <span className="tabular">
                      {formatInr(plan.deployable * t.share, { compact: true })}{' '}
                      <span className="text-muted text-xs">({(t.share * 100).toFixed(0)}%)</span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </CardBody>
    </Card>
  )
}

function Summary({ plan }: { plan: InvestmentPlan }) {
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Deploying now"
          value={formatInr(plan.invested, { compact: true })}
          hint={`${plan.positions} positions`}
        />
        <Stat
          label="Held back"
          value={formatInr(plan.cash_reserve, { compact: true })}
          hint={`${(100 - plan.deploy_pct).toFixed(0)}% of capital, for later tranches`}
        />
        <Stat
          label="At risk to stops"
          value={formatInr(plan.total_risk_amount, { compact: true })}
          hint={`${plan.total_risk_pct}% of capital if every stop is hit`}
          tone={plan.total_risk_pct > 8 ? 'warning' : 'default'}
        />
        <Stat
          label="Left over"
          value={formatInr(plan.uninvested_cash, { compact: true })}
          hint="Whole-share rounding"
        />
      </div>

      {plan.sector_exposure.length ? (
        <p className="text-muted text-xs">
          Largest sector exposure:{' '}
          {plan.sector_exposure
            .slice(0, 3)
            .map((s) => `${s.sector} ${s.pct}%`)
            .join(' · ')}
          {plan.sector_exposure.length > 3 ? ` · +${plan.sector_exposure.length - 3} more` : ''}
        </p>
      ) : null}
    </>
  )
}

function Allocations({
  plan,
  onSwap,
}: {
  plan: InvestmentPlan
  onSwap: (symbol: string) => void
}) {
  return (
    <Card>
      <CardHeader
        title="What to buy"
        description={`Whole shares at the last close. Prices as of ${plan.as_of}.`}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-muted border-b text-xs">
            <tr>
              <th className="px-6 py-3 text-left font-medium">Company</th>
              <th className="px-6 py-3 text-right font-medium">Price</th>
              <th className="px-6 py-3 text-right font-medium">Shares</th>
              <th className="px-6 py-3 text-right font-medium">Amount</th>
              <th className="px-6 py-3 text-right font-medium">Weight</th>
              <th className="px-6 py-3 text-right font-medium">Stop</th>
              <th className="px-2 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {plan.allocations.map((a) => (
              <AllocationRow key={a.symbol} a={a} onSwap={() => onSwap(a.symbol)} />
            ))}
          </tbody>
          <tfoot>
            <tr className="surface-2 font-medium">
              <td className="px-4 py-2.5">Total</td>
              <td />
              <td />
              <td className="tabular px-4 py-2.5 text-right">{formatInr(plan.invested)}</td>
              <td className="tabular px-4 py-2.5 text-right">100%</td>
              <td colSpan={2} />
            </tr>
          </tfoot>
        </table>
      </div>

      {plan.skipped.length ? (
        <CardBody className="border-t">
          <p className="text-muted mb-1 text-xs font-medium">Left out</p>
          {plan.skipped.map((s) => (
            <p key={s.symbol} className="text-muted text-xs">
              <span className="text-[var(--text)]">{s.symbol}</span> — {s.reason}
            </p>
          ))}
        </CardBody>
      ) : null}
    </Card>
  )
}

function AllocationRow({ a, onSwap }: { a: Allocation; onSwap: () => void }) {
  const weight = a.actual_weight_pct ?? a.target_weight_pct
  return (
    <tr className="hover:surface-2 border-b last:border-0 align-top">
      <td className="px-4 py-3">
        <div className="font-medium">{a.symbol}</div>
        <div className="text-muted truncate text-xs">{a.name}</div>
        {a.warning ? (
          <div className="text-[var(--warn)] mt-1 flex items-start gap-1 text-xs">
            <TriangleAlert className="mt-0.5 h-3 w-3 shrink-0" />
            <span>{a.warning}</span>
          </div>
        ) : null}
      </td>
      <td className="tabular px-4 py-3 text-right">{formatNumber(a.price, 1)}</td>
      <td className="tabular px-4 py-3 text-right font-medium">{a.shares}</td>
      <td className="tabular px-4 py-3 text-right">{formatInr(a.value, { compact: true })}</td>
      <td className="tabular px-4 py-3 text-right">{weight.toFixed(1)}%</td>
      <td className="tabular px-4 py-3 text-right">
        {a.stop ? (
          <>
            <div>{formatNumber(a.stop, 0)}</div>
            <div className="text-muted text-xs">{a.stop_distance_pct}%</div>
          </>
        ) : (
          <span className="text-muted">—</span>
        )}
      </td>
      <td className="px-2 py-3">
        <button
          onClick={onSwap}
          title="Swap this out for the next candidate"
          className={cn('text-muted hover:text-[var(--accent)]')}
          aria-label={`Swap out ${a.symbol}`}
        >
          <Repeat className="h-3.5 w-3.5" />
        </button>
      </td>
    </tr>
  )
}
