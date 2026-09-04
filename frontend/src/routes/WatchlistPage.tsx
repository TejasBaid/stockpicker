import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Star, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { PageHeader } from '@/components/layout/AppShell'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { portfolioApi, screenerApi, watchlistApi } from '@/lib/api'

export default function WatchlistPage() {
  const qc = useQueryClient()
  const [symbol, setSymbol] = useState('')

  const { data, isPending } = useQuery({ queryKey: ['watchlist'], queryFn: watchlistApi.get })
  const { data: catalogue } = useQuery({
    queryKey: ['screener', 'factors'],
    queryFn: screenerApi.factors,
    staleTime: Infinity,
  })
  const { data: matches } = useQuery({
    queryKey: ['instruments', symbol],
    queryFn: () => portfolioApi.searchInstruments(symbol),
    enabled: symbol.length >= 2,
  })

  const labels = new Map<string, string>()
  Object.values(catalogue?.categories ?? {}).forEach((list) =>
    list.forEach((f) => labels.set(f.name, f.label)),
  )

  const add = useMutation({
    mutationFn: () => watchlistApi.add(symbol),
    onSuccess: () => {
      setSymbol('')
      qc.invalidateQueries({ queryKey: ['watchlist'] })
    },
  })
  const remove = useMutation({
    mutationFn: watchlistApi.remove,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist'] }),
  })

  const factors = data?.factors ?? []

  return (
    <>
      <PageHeader
        title="Watchlist"
        description="Names you're tracking, with where they currently rank."
      />
      <div className="space-y-5 p-6">
        <Card>
          <CardBody className="flex flex-wrap items-end gap-3">
            <div className="min-w-48">
              <label htmlFor="wsym" className="mb-1.5 block text-sm font-medium">
                Add a symbol
              </label>
              <Input
                id="wsym"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                placeholder="RELIANCE"
                list="watch-matches"
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && symbol) add.mutate()
                }}
              />
              <datalist id="watch-matches">
                {matches?.map((m) => (
                  <option key={m.symbol} value={m.symbol}>
                    {m.name}
                  </option>
                ))}
              </datalist>
            </div>
            <Button onClick={() => add.mutate()} disabled={!symbol || add.isPending}>
              {add.isPending ? <Spinner /> : <Plus className="h-4 w-4" />}
              Add
            </Button>
            {add.isError ? (
              <span className="text-neg text-sm">{(add.error as Error).message}</span>
            ) : null}
          </CardBody>
        </Card>

        {isPending ? (
          <div className="text-muted flex items-center gap-2 text-sm">
            <Spinner /> Loading…
          </div>
        ) : !data?.items.length ? (
          <Alert tone="info">
            <span className="flex items-center gap-2">
              <Star className="h-4 w-4" /> Nothing on the watchlist yet.
            </span>
          </Alert>
        ) : (
          <Card>
            <CardHeader
              title={`${data.items.length} watched`}
              description={
                data.as_of ? `Factor deciles as of ${data.as_of} — 1 is best, 10 is worst.` : undefined
              }
            />
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-muted border-b text-xs">
                  <tr>
                    <th className="px-4 py-2.5 text-left font-medium">Company</th>
                    <th className="px-4 py-2.5 text-left font-medium">Sector</th>
                    {factors.map((f) => (
                      <th key={f} className="px-4 py-2.5 text-center font-medium">
                        {labels.get(f) ?? f}
                      </th>
                    ))}
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <tr key={item.symbol} className="border-b last:border-0">
                      <td className="px-4 py-3">
                        <div className="font-medium">{item.symbol}</div>
                        <div className="text-muted truncate text-xs">{item.name}</div>
                      </td>
                      <td className="text-muted px-4 py-3 text-xs">{item.sector}</td>
                      {factors.map((f) => {
                        const d = item.deciles[f]
                        return (
                          <td key={f} className="px-4 py-3 text-center">
                            {d == null ? (
                              <span className="text-muted">—</span>
                            ) : (
                              <Badge tone={d <= 3 ? 'ok' : d >= 8 ? 'fail' : 'muted'}>D{d}</Badge>
                            )}
                          </td>
                        )
                      })}
                      <td className="px-2 py-3">
                        <button
                          onClick={() => remove.mutate(item.symbol)}
                          className="text-muted hover:text-neg"
                          aria-label={`Remove ${item.symbol}`}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </div>
    </>
  )
}
