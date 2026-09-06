import type { ReactNode } from 'react'
import { ArrowDownRight, ArrowUpRight } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Dims the fractional part so magnitude reads first.
 *
 * Only true two-digit decimals at the very end qualify. In compact notation
 * the digits after the point carry magnitude, not precision -- dimming the "4"
 * in "Rs 3.4L" would grey out a third of the number's value.
 */
function Figure({ value }: { value: ReactNode }) {
  if (typeof value !== 'string') {
    return <span>{value}</span>
  }
  const match = value.match(/^(.*)(\.\d{2})$/)
  if (!match) return <span>{value}</span>
  const [, head, decimals] = match
  return (
    <span>
      {head}
      <span className="text-dim">{decimals}</span>
    </span>
  )
}

export function Delta({ value, suffix = '%' }: { value: number; suffix?: string }) {
  const positive = value >= 0
  const Icon = positive ? ArrowUpRight : ArrowDownRight
  return (
    <span
      className={cn(
        'tabular inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-xs font-medium',
        positive ? 'text-pos' : 'text-neg',
      )}
      style={{ background: positive ? 'var(--pos-soft)' : 'var(--neg-soft)' }}
    >
      <Icon className="h-3 w-3" />
      {Math.abs(value).toFixed(2)}
      {suffix}
    </span>
  )
}

export function Stat({
  label,
  value,
  hint,
  delta,
  tone = 'default',
  className,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  delta?: number
  tone?: 'default' | 'positive' | 'negative' | 'warning'
  className?: string
}) {
  const toneClass =
    tone === 'positive'
      ? 'text-pos'
      : tone === 'negative'
        ? 'text-neg'
        : tone === 'warning'
          ? 'text-[var(--warn)]'
          : ''
  return (
    <div className={cn('surface rounded-card border px-5 py-4', className)}>
      <p className="text-muted text-xs font-medium">{label}</p>
      <p
        className={cn(
          'tabular mt-2 text-[26px] font-semibold leading-none tracking-tight',
          toneClass,
        )}
      >
        <Figure value={value} />
      </p>
      <div className="mt-2 flex items-center gap-2">
        {delta !== undefined ? <Delta value={delta} /> : null}
        {hint ? <span className="text-muted text-xs">{hint}</span> : null}
      </div>
    </div>
  )
}

export function Meter({
  pct,
  tone = 'accent',
  className,
}: {
  pct: number
  tone?: 'accent' | 'warn' | 'neg' | 'pos'
  className?: string
}) {
  const color =
    tone === 'neg'
      ? 'var(--neg)'
      : tone === 'warn'
        ? 'var(--warn)'
        : tone === 'pos'
          ? 'var(--pos)'
          : 'var(--accent)'
  return (
    <div
      className={cn('surface-3 h-1.5 w-full overflow-hidden rounded-full', className)}
      role="presentation"
    >
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${Math.min(100, Math.max(0, pct))}%`, background: color }}
      />
    </div>
  )
}

/** Multi-segment allocation bar, as used for exposure breakdowns. */
export function SegmentBar({
  segments,
}: {
  segments: { label: string; pct: number; color?: string }[]
}) {
  const palette = [
    'var(--accent)',
    'color-mix(in oklab, var(--accent) 70%, white)',
    'color-mix(in oklab, var(--accent) 45%, white)',
    'color-mix(in oklab, var(--accent) 25%, white)',
  ]
  return (
    <div className="surface-3 flex h-2 w-full gap-0.5 overflow-hidden rounded-full">
      {segments.map((s, i) => (
        <div
          key={s.label}
          title={`${s.label} ${s.pct}%`}
          style={{ width: `${s.pct}%`, background: s.color ?? palette[i % palette.length] }}
          className="h-full first:rounded-l-full last:rounded-r-full"
        />
      ))}
    </div>
  )
}
