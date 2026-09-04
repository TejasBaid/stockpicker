import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bookmark, Download, Play, SlidersHorizontal } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { PageHeader } from '@/components/layout/AppShell'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Spinner } from '@/components/ui/spinner'
import {
  screenerApi,
  strategyApi,
  type FactorMeta,
  type Preset,
  type ScreenResponse,
} from '@/lib/api'
import { cn, formatNumber } from '@/lib/utils'

const CATEGORY_ORDER = [
  'value',
  'quality',
  'growth',
  'momentum',
  'revisions',
  'risk',
  'ownership',
] as const

export default function Screener() {
  const qc = useQueryClient()
  const { data: catalogue } = useQuery({
    queryKey: ['screener', 'factors'],
    queryFn: screenerApi.factors,
    staleTime: Infinity,
  })
  const { data: presetData } = useQuery({
    queryKey: ['screener', 'presets'],
    queryFn: screenerApi.presets,
    staleTime: Infinity,
  })

  const [activePreset, setActivePreset] = useState<string | null>(null)
  const [weights, setWeights] = useState<Record<string, number>>({})
  const [filters, setFilters] = useState<Preset['filters']>([])
  const [limit, setLimit] = useState(25)
  const [maxPerSector, setMaxPerSector] = useState<number | null>(4)
  const [showFactors, setShowFactors] = useState(false)
  const [savedName, setSavedName] = useState<string | null>(null)

  const screen = useMutation({ mutationFn: screenerApi.run })

  const { data: saved } = useQuery({ queryKey: ['strategies'], queryFn: strategyApi.list })

  const saveStrategy = useMutation({
    mutationFn: (name: string) =>
      strategyApi.save({ name, weights, filters, max_per_sector: maxPerSector, limit }),
    onSuccess: (s) => {
      setSavedName(s.name)
      qc.invalidateQueries({ queryKey: ['strategies'] })
      setTimeout(() => setSavedName(null), 4000)
    },
  })

  const factorsByName = useMemo(() => {
    const map = new Map<string, FactorMeta>()
    Object.values(catalogue?.categories ?? {}).forEach((list) =>
      list.forEach((f) => map.set(f.name, f)),
    )
    return map
  }, [catalogue])

  // Start on the first preset so the page is useful before any configuration.
  useEffect(() => {
    if (!activePreset && presetData?.presets.length) {
      const first = presetData.presets[0]
      setActivePreset(first.slug)
      setWeights(first.weights)
      setFilters(first.filters)
    }
  }, [presetData, activePreset])

  useEffect(() => {
    if (Object.keys(weights).length) {
      screen.mutate({ weights, filters, limit, max_per_sector: maxPerSector })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [weights, filters, limit, maxPerSector])

  function applyPreset(p: Preset) {
    setActivePreset(p.slug)
    setWeights(p.weights)
    setFilters(p.filters)
  }

  function setWeight(name: string, value: number) {
    setActivePreset(null)
    setWeights((w) => {
      const next = { ...w }
      if (value <= 0) delete next[name]
      else next[name] = value
      return next
    })
  }

  const result = screen.data
  const weightSum = Object.values(weights).reduce((a, b) => a + Math.abs(b), 0)

  return (
    <>
      <PageHeader
        title="Screener"
        description="Rank the Nifty 200 by any combination of factors. Scores are point-in-time."
        action={
          <div className="flex items-center gap-2">
            {savedName ? (
              <span className="text-pos text-xs">Saved “{savedName}”</span>
            ) : null}
            <Button
              variant="secondary"
              size="sm"
              disabled={!Object.keys(weights).length || saveStrategy.isPending}
              onClick={() => {
                const name = window.prompt('Name this strategy')
                if (name) saveStrategy.mutate(name)
              }}
            >
              <Bookmark className="h-3.5 w-3.5" />
              Save as strategy
            </Button>
            {result ? (
              <Button variant="secondary" size="sm" onClick={() => exportCsv(result)}>
                <Download className="h-3.5 w-3.5" />
                Export
              </Button>
            ) : null}
          </div>
        }
      />

      <div className="space-y-5 p-6">
        <Card>
          <CardHeader
            title="Strategy"
            description="Start from a preset, then adjust the weights."
            action={
              <Button variant="ghost" size="sm" onClick={() => setShowFactors((s) => !s)}>
                <SlidersHorizontal className="h-3.5 w-3.5" />
                {showFactors ? 'Hide factors' : 'Customise factors'}
              </Button>
            }
          />
          <CardBody className="space-y-4">
            <div className="flex flex-wrap gap-2">
              {saved?.map((s) => (
                <button
                  key={s.id}
                  onClick={() => {
                    setActivePreset(null)
                    setWeights(s.weights)
                    setFilters(s.filters as Preset['filters'])
                  }}
                  title={`Your saved strategy · v${s.version}`}
                  className="rounded-md border border-[var(--accent)]/40 px-3 py-1.5 text-sm text-[var(--accent)] transition-colors hover:bg-[var(--accent)]/10"
                >
                  {s.name}
                </button>
              ))}
              {presetData?.presets.map((p) => (
                <button
                  key={p.slug}
                  onClick={() => applyPreset(p)}
                  title={p.description}
                  className={cn(
                    'rounded-md border px-3 py-1.5 text-sm transition-colors',
                    activePreset === p.slug
                      ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
                      : 'text-muted hover:surface-2 hover:text-[var(--text)]',
                  )}
                >
                  {p.name}
                </button>
              ))}
            </div>

            {activePreset ? (
              <p className="text-muted text-sm">
                {presetData?.presets.find((p) => p.slug === activePreset)?.description}
              </p>
            ) : (
              <p className="text-muted text-sm">
                Custom weighting across {Object.keys(weights).length} factors.
              </p>
            )}

            <div className="flex flex-wrap items-center gap-4 border-t pt-4 text-sm">
              <label className="flex items-center gap-2">
                <span className="text-muted">Show</span>
                <select
                  value={limit}
                  onChange={(e) => setLimit(Number(e.target.value))}
                  className="surface-2 rounded-md border px-2 py-1 text-sm"
                >
                  {[10, 25, 50, 100].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-2">
                <span className="text-muted">Max per sector</span>
                <select
                  value={maxPerSector ?? ''}
                  onChange={(e) =>
                    setMaxPerSector(e.target.value === '' ? null : Number(e.target.value))
                  }
                  className="surface-2 rounded-md border px-2 py-1 text-sm"
                >
                  <option value="">No limit</option>
                  {[2, 3, 4, 5, 8].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              {screen.isPending ? (
                <span className="text-muted flex items-center gap-1.5 text-xs">
                  <Spinner className="h-3 w-3" /> Ranking…
                </span>
              ) : result ? (
                <span className="text-muted text-xs">
                  {result.eligible} of {result.universe_size} passed the filters · as of{' '}
                  {result.as_of}
                </span>
              ) : null}
            </div>

            {showFactors && catalogue ? (
              <div className="space-y-5 border-t pt-4">
                {CATEGORY_ORDER.filter((c) => catalogue.categories[c]).map((category) => (
                  <div key={category}>
                    <h3 className="text-muted mb-2 text-xs font-semibold uppercase tracking-wide">
                      {category}
                    </h3>
                    <div className="grid gap-x-6 gap-y-2 sm:grid-cols-2 xl:grid-cols-3">
                      {catalogue.categories[category].map((f) => (
                        <WeightRow
                          key={f.name}
                          factor={f}
                          value={weights[f.name] ?? 0}
                          onChange={(v) => setWeight(f.name, v)}
                        />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
          </CardBody>
        </Card>

        {screen.isError ? <Alert tone="error">{(screen.error as Error).message}</Alert> : null}

        {result ? (
          <>
            <CoverageNotice result={result} factorsByName={factorsByName} />
            <ResultsTable result={result} factorsByName={factorsByName} weightSum={weightSum} />
          </>
        ) : screen.isPending ? null : (
          <Card>
            <CardBody className="text-muted flex items-center gap-2 text-sm">
              <Play className="h-4 w-4" /> Choose a strategy to run a screen.
            </CardBody>
          </Card>
        )}
      </div>
    </>
  )
}

function WeightRow({
  factor,
  value,
  onChange,
}: {
  factor: FactorMeta
  value: number
  onChange: (v: number) => void
}) {
  return (
    <label className="flex items-center gap-3" title={factor.description}>
      <input
        type="range"
        min={0}
        max={0.5}
        step={0.05}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-24 accent-[var(--accent)]"
      />
      <span className={cn('flex-1 truncate text-sm', value > 0 ? '' : 'text-muted')}>
        {factor.label}
      </span>
      <span className="tabular text-muted w-9 text-right text-xs">
        {value > 0 ? value.toFixed(2) : '—'}
      </span>
    </label>
  )
}

function CoverageNotice({
  result,
  factorsByName,
}: {
  result: ScreenResponse
  factorsByName: Map<string, FactorMeta>
}) {
  const weak = Object.entries(result.coverage)
    .filter(([, pct]) => pct < 70)
    .sort((a, b) => a[1] - b[1])
  if (!weak.length) return null
  return (
    <Alert tone="info">
      <span className="text-sm">
        Thin data on{' '}
        {weak
          .map(([name, pct]) => `${factorsByName.get(name)?.label ?? name} (${pct}%)`)
          .join(', ')}
        . Names missing a factor score neutrally on it rather than being dropped, so they are
        neither rewarded nor punished for the gap.
      </span>
    </Alert>
  )
}

function ResultsTable({
  result,
  factorsByName,
  weightSum,
}: {
  result: ScreenResponse
  factorsByName: Map<string, FactorMeta>
  weightSum: number
}) {
  const factorNames = Object.keys(result.weights).sort(
    (a, b) => (result.weights[b] ?? 0) - (result.weights[a] ?? 0),
  )
  return (
    <Card>
      <CardHeader
        title={`${result.returned} results`}
        description={`Weighted across ${factorNames.length} factors (total weight ${weightSum.toFixed(2)}), scored within sector.`}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-muted border-b text-xs">
            <tr>
              <th className="px-4 py-2.5 text-right font-medium">#</th>
              <th className="px-4 py-2.5 text-left font-medium">Company</th>
              <th className="px-4 py-2.5 text-left font-medium">Sector</th>
              <th className="px-4 py-2.5 text-right font-medium">Score</th>
              {factorNames.map((n) => (
                <th
                  key={n}
                  className="px-3 py-2.5 text-right font-medium"
                  title={factorsByName.get(n)?.description}
                >
                  {factorsByName.get(n)?.label ?? n}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.results.map((row) => (
              <tr key={row.symbol} className="hover:surface-2 border-b last:border-0">
                <td className="tabular text-muted px-4 py-2.5 text-right text-xs">{row.rank}</td>
                <td className="px-4 py-2.5">
                  <div className="font-medium">{row.symbol}</div>
                  <div className="text-muted truncate text-xs">{row.name}</div>
                </td>
                <td className="text-muted px-4 py-2.5 text-xs">{row.sector}</td>
                <td className="tabular px-4 py-2.5 text-right font-semibold">
                  {row.composite.toFixed(3)}
                </td>
                {factorNames.map((n) => {
                  const cell = row.factors[n]
                  return (
                    <td key={n} className="tabular px-3 py-2.5 text-right">
                      <span>{cell?.raw != null ? formatNumber(cell.raw, 1) : '—'}</span>
                      {cell?.decile != null ? (
                        <DecileDot decile={cell.decile} />
                      ) : null}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function DecileDot({ decile }: { decile: number }) {
  const tone = decile <= 3 ? 'ok' : decile >= 8 ? 'fail' : 'muted'
  return (
    <Badge tone={tone} className="ml-1.5 px-1.5 py-0 text-[10px]">
      D{decile}
    </Badge>
  )
}

function exportCsv(result: ScreenResponse) {
  const factorNames = Object.keys(result.weights)
  const header = ['rank', 'symbol', 'name', 'sector', 'score', ...factorNames]
  const lines = result.results.map((r) =>
    [
      r.rank,
      r.symbol,
      `"${(r.name ?? '').replace(/"/g, '""')}"`,
      `"${(r.sector ?? '').replace(/"/g, '""')}"`,
      r.composite,
      ...factorNames.map((n) => r.factors[n]?.raw ?? ''),
    ].join(','),
  )
  const blob = new Blob([[header.join(','), ...lines].join('\n')], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `screen-${result.as_of}.csv`
  a.click()
  URL.revokeObjectURL(url)
}
