import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function Stat({
  label,
  value,
  hint,
  tone = 'default',
  className,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
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
    <div className={cn('surface rounded-lg border px-4 py-3.5', className)}>
      <p className="text-muted text-xs font-medium">{label}</p>
      <p className={cn('tabular mt-1 text-2xl font-semibold tracking-tight', toneClass)}>{value}</p>
      {hint ? <p className="text-muted mt-0.5 text-xs">{hint}</p> : null}
    </div>
  )
}

export function Meter({ pct, tone = 'accent' }: { pct: number; tone?: 'accent' | 'warn' | 'neg' }) {
  const color =
    tone === 'neg' ? 'var(--neg)' : tone === 'warn' ? 'var(--warn)' : 'var(--accent)'
  return (
    <div className="surface-2 h-1.5 w-full overflow-hidden rounded-full" role="presentation">
      <div
        className="h-full rounded-full transition-all"
        style={{ width: `${Math.min(100, Math.max(0, pct))}%`, background: color }}
      />
    </div>
  )
}
