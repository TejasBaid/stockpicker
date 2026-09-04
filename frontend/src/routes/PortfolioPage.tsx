import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Plus, Trash2, TrendingDown, TrendingUp } from 'lucide-react'
import { useState } from 'react'
import { PageHeader } from '@/components/layout/AppShell'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { Stat } from '@/components/ui/stat'
import { portfolioApi, type Holding } from '@/lib/api'
import { cn, formatInr, formatNumber, formatPercent } from '@/lib/utils'

export default function PortfolioPage() {
  const qc = useQueryClient()
  const [selected, setSelected] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)

  const { data: portfolios, isPending } = useQuery({
    queryKey: ['portfolios'],
    queryFn: portfolioApi.list,
  })

  const active = selected ?? portfolios?.[0]?.id ?? null

  const { data: detail } = useQuery({
    queryKey: ['portfolio', active],
    queryFn: () => portfolioApi.get(active as string),
    enabled: !!active,
  })
  const { data: alerts } = useQuery({
    queryKey: ['portfolio', active, 'alerts'],
    queryFn: () => portfolioApi.alerts(active as string),
    enabled: !!active,
  })

  const create = useMutation({
    mutationFn: portfolioApi.create,
    onSuccess: (p) => {
      setSelected(p.id)
      qc.invalidateQueries({ queryKey: ['portfolios'] })
    },
  })

  if (isPending) {
    return (
      <>
        <PageHeader title="Portfolio" />
        <div className="text-muted flex items-center gap-2 p-6 text-sm">
          <Spinner /> Loading…
        </div>
      </>
    )
  }

  if (!portfolios?.length) {
    return (
      <>
        <PageHeader title="Portfolio" description="Track positions and plan exits." />
        <div className="p-6">
          <Card>
            <CardBody className="space-y-4">
              <div>
                <p className="text-sm font-medium">No portfolio yet</p>
                <p className="text-muted mt-1 text-sm">
                  Positions are entered by hand. This platform never reads your brokerage
                  account.
                </p>
              </div>
              <Button
                onClick={() => create.mutate({ name: 'Main portfolio', cash: 0 })}
                disabled={create.isPending}
              >
                {create.isPending ? <Spinner /> : <Plus className="h-4 w-4" />}
                Create a portfolio
              </Button>
            </CardBody>
          </Card>
        </div>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Portfolio"
        description="Positions, exit plans and tax treatment. Entered by hand — your broker is never read."
        action={
          <Button size="sm" onClick={() => setAdding((v) => !v)}>
            <Plus className="h-3.5 w-3.5" />
            Add position
          </Button>
        }
      />

      <div className="space-y-5 p-6">
        {detail ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Total value" value={formatInr(detail.total_value, { compact: true })} />
            <Stat
              label="Unrealised P&L"
              value={formatInr(detail.pnl, { compact: true })}
              hint={formatPercent(detail.pnl_pct)}
              tone={detail.pnl >= 0 ? 'positive' : 'negative'}
            />
            <Stat label="Invested" value={formatInr(detail.invested, { compact: true })} />
            <Stat
              label="Estimated tax"
              value={formatInr(detail.tax.estimated_tax, { compact: true })}
              hint={`ST ${formatInr(detail.tax.short_term_gain, { compact: true })} · LT ${formatInr(detail.tax.long_term_gain, { compact: true })}`}
            />
          </div>
        ) : null}

        {adding && active ? (
          <AddPosition
            portfolioId={active}
            onDone={() => {
              setAdding(false)
              qc.invalidateQueries({ queryKey: ['portfolio', active] })
            }}
          />
        ) : null}

        {alerts?.length ? (
          <Card>
            <CardHeader title="Needs attention" description="Triggers from your own exit plans." />
            <div className="divide-y">
              {alerts.map((a, i) => (
                <div key={i} className="flex items-start gap-2.5 px-5 py-3 text-sm">
                  <AlertTriangle
                    className={cn(
                      'mt-0.5 h-4 w-4 shrink-0',
                      a.kind === 'exit' ? 'text-neg' : a.kind === 'tax' ? 'text-muted' : 'text-[var(--warn)]',
                    )}
                  />
                  <span className="font-medium">{a.symbol}</span>
                  <span className="text-muted">{a.message}</span>
                </div>
              ))}
            </div>
          </Card>
        ) : null}

        {detail?.holdings.length ? (
          <Card>
            <CardHeader title={`${detail.holdings.length} holdings`} />
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-muted border-b text-xs">
                  <tr>
                    <th className="px-4 py-2.5 text-left font-medium">Company</th>
                    <th className="px-4 py-2.5 text-right font-medium">Qty</th>
                    <th className="px-4 py-2.5 text-right font-medium">Avg</th>
                    <th className="px-4 py-2.5 text-right font-medium">Last</th>
                    <th className="px-4 py-2.5 text-right font-medium">Value</th>
                    <th className="px-4 py-2.5 text-right font-medium">P&L</th>
                    <th className="px-4 py-2.5 text-right font-medium">Weight</th>
                    <th className="px-4 py-2.5 text-left font-medium">Tax</th>
                    <th className="px-4 py-2.5 text-left font-medium">Exit plan</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.holdings.map((h) => (
                    <HoldingRow key={h.id} holding={h} portfolioId={active as string} />
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        ) : detail ? (
          <Alert tone="info">No positions yet. Add one to start tracking.</Alert>
        ) : null}

        {detail ? (
          <p className="text-muted text-xs">{detail.tax.note}</p>
        ) : null}
      </div>
    </>
  )
}

function HoldingRow({ holding: h, portfolioId }: { holding: Holding; portfolioId: string }) {
  const qc = useQueryClient()
  const remove = useMutation({
    mutationFn: () => portfolioApi.removePosition(portfolioId, h.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['portfolio', portfolioId] }),
  })
  const decayed = h.factor_drift.filter((d) => d.drift >= 3)

  return (
    <tr className="border-b align-top last:border-0">
      <td className="px-4 py-3">
        <div className="font-medium">{h.symbol}</div>
        <div className="text-muted truncate text-xs">{h.name}</div>
        {decayed.length ? (
          <div className="text-[var(--warn)] mt-1 text-xs">
            {decayed[0].factor} decile {decayed[0].entry_decile} → {decayed[0].current_decile}
          </div>
        ) : null}
      </td>
      <td className="tabular px-4 py-3 text-right">{formatNumber(h.quantity, 0)}</td>
      <td className="tabular px-4 py-3 text-right">{formatNumber(h.avg_price)}</td>
      <td className="tabular px-4 py-3 text-right">{formatNumber(h.last_price)}</td>
      <td className="tabular px-4 py-3 text-right">{formatInr(h.market_value, { compact: true })}</td>
      <td
        className={cn(
          'tabular px-4 py-3 text-right font-medium',
          h.pnl >= 0 ? 'text-pos' : 'text-neg',
        )}
      >
        <div className="flex items-center justify-end gap-1">
          {h.pnl >= 0 ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
          {formatPercent(h.pnl_pct)}
        </div>
        <div className="text-muted text-xs">{formatInr(h.pnl, { compact: true })}</div>
      </td>
      <td className="tabular px-4 py-3 text-right">{h.weight_pct}%</td>
      <td className="px-4 py-3">
        <Badge tone={h.tax_status === 'long-term' ? 'ok' : 'muted'}>{h.tax_status}</Badge>
        {h.days_to_long_term > 0 ? (
          <div className="text-muted mt-1 text-xs">{h.days_to_long_term}d to LT</div>
        ) : null}
      </td>
      <td className="px-4 py-3 text-xs">
        {h.exit_plan ? (
          <div className="space-y-0.5">
            {h.exit_plan.stop_price ? (
              <div className={h.exit_plan.triggers.length ? 'text-neg font-medium' : 'text-muted'}>
                Stop {formatNumber(h.exit_plan.stop_price)}
                {h.exit_plan.stop_distance_pct != null
                  ? ` (${h.exit_plan.stop_distance_pct}%)`
                  : ''}
              </div>
            ) : null}
            {h.exit_plan.triggers.map((t, i) => (
              <div key={i} className="text-neg">
                {t}
              </div>
            ))}
          </div>
        ) : (
          <span className="text-muted">—</span>
        )}
      </td>
      <td className="px-2 py-3">
        <button
          onClick={() => remove.mutate()}
          className="text-muted hover:text-neg"
          aria-label={`Remove ${h.symbol}`}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </td>
    </tr>
  )
}

function AddPosition({ portfolioId, onDone }: { portfolioId: string; onDone: () => void }) {
  const [symbol, setSymbol] = useState('')
  const [quantity, setQuantity] = useState('')
  const [price, setPrice] = useState('')
  const [openedOn, setOpenedOn] = useState(new Date().toISOString().slice(0, 10))
  const [thesis, setThesis] = useState('')

  const { data: matches } = useQuery({
    queryKey: ['instruments', symbol],
    queryFn: () => portfolioApi.searchInstruments(symbol),
    enabled: symbol.length >= 2,
  })

  const add = useMutation({
    mutationFn: () =>
      portfolioApi.addPosition(portfolioId, {
        symbol,
        quantity: Number(quantity),
        avg_price: Number(price),
        opened_on: openedOn,
        thesis: thesis || undefined,
      }),
    onSuccess: onDone,
  })

  return (
    <Card>
      <CardHeader title="Add a position" />
      <CardBody className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Symbol" htmlFor="sym">
            <Input
              id="sym"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              placeholder="RELIANCE"
              list="instrument-matches"
            />
            <datalist id="instrument-matches">
              {matches?.map((m) => (
                <option key={m.symbol} value={m.symbol}>
                  {m.name}
                </option>
              ))}
            </datalist>
          </Field>
          <Field label="Quantity" htmlFor="qty">
            <Input id="qty" type="number" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          </Field>
          <Field label="Average price" htmlFor="px">
            <Input id="px" type="number" value={price} onChange={(e) => setPrice(e.target.value)} />
          </Field>
          <Field label="Bought on" htmlFor="on">
            <Input id="on" type="date" value={openedOn} onChange={(e) => setOpenedOn(e.target.value)} />
          </Field>
        </div>
        <Field label="Thesis" htmlFor="thesis" hint="Why you bought it — worth writing down now.">
          <Input id="thesis" value={thesis} onChange={(e) => setThesis(e.target.value)} />
        </Field>
        {add.isError ? <Alert tone="error">{(add.error as Error).message}</Alert> : null}
        <div className="flex gap-2">
          <Button onClick={() => add.mutate()} disabled={add.isPending || !symbol || !quantity || !price}>
            {add.isPending ? <Spinner /> : null}
            Add
          </Button>
          <Button variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}
