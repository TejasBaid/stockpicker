import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Beaker, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/AppShell'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Spinner } from '@/components/ui/spinner'
import { screenerApi, strategyApi, type SavedStrategy } from '@/lib/api'

export default function Strategies() {
  const qc = useQueryClient()
  const { data: strategies, isPending } = useQuery({
    queryKey: ['strategies'],
    queryFn: strategyApi.list,
  })
  const { data: catalogue } = useQuery({
    queryKey: ['screener', 'factors'],
    queryFn: screenerApi.factors,
    staleTime: Infinity,
  })

  const labels = new Map<string, string>()
  Object.values(catalogue?.categories ?? {}).forEach((list) =>
    list.forEach((f) => labels.set(f.name, f.label)),
  )

  const remove = useMutation({
    mutationFn: strategyApi.remove,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['strategies'] }),
  })

  return (
    <>
      <PageHeader
        title="Strategies"
        description="Your saved factor weightings. Save one from the screener once you like a combination."
      />
      <div className="space-y-4 px-7 pb-8">
        {isPending ? (
          <div className="text-muted flex items-center gap-2 text-sm">
            <Spinner /> Loading…
          </div>
        ) : !strategies?.length ? (
          <Alert tone="info">
            Nothing saved yet. Build a weighting on the Screener, then use “Save as strategy”.
            Saving again bumps the version rather than overwriting, so a backtest always refers
            to the exact definition that produced it.
          </Alert>
        ) : (
          strategies.map((s) => (
            <StrategyCard
              key={s.id}
              strategy={s}
              labels={labels}
              onDelete={() => remove.mutate(s.id)}
            />
          ))
        )}
      </div>
    </>
  )
}

function StrategyCard({
  strategy,
  labels,
  onDelete,
}: {
  strategy: SavedStrategy
  labels: Map<string, string>
  onDelete: () => void
}) {
  const weights = Object.entries(strategy.weights).sort((a, b) => b[1] - a[1])
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Beaker className="h-4 w-4" />
            {strategy.name}
            <Badge tone="muted">v{strategy.version}</Badge>
          </span>
        }
        description={strategy.description ?? undefined}
        action={
          <button onClick={onDelete} className="text-muted hover:text-neg" aria-label="Delete">
            <Trash2 className="h-4 w-4" />
          </button>
        }
      />
      <CardBody className="space-y-3">
        <div className="flex flex-wrap gap-2">
          {weights.map(([name, weight]) => (
            <span
              key={name}
              className="surface-2 rounded-md border px-2 py-1 text-xs"
              title={name}
            >
              {labels.get(name) ?? name}{' '}
              <span className="tabular text-muted">{weight.toFixed(2)}</span>
            </span>
          ))}
        </div>
        {strategy.filters.length ? (
          <p className="text-muted text-xs">
            Gates:{' '}
            {strategy.filters
              .map(
                (f) =>
                  `${labels.get(f.factor) ?? f.factor} ${
                    { gt: '>', gte: '≥', lt: '<', lte: '≤' }[f.op] ?? f.op
                  } ${f.value}`,
              )
              .join(' · ')}
          </p>
        ) : null}
      </CardBody>
    </Card>
  )
}
