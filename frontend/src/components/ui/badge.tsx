import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

const tones = {
  ok: 'text-pos',
  fail: 'text-neg',
  warn: 'text-[var(--warn)]',
  accent: 'text-[var(--accent)]',
  muted: 'text-muted',
}

const backgrounds: Record<keyof typeof tones, string> = {
  ok: 'var(--pos-soft)',
  fail: 'var(--neg-soft)',
  warn: 'var(--warn-soft)',
  accent: 'var(--accent-soft)',
  muted: 'var(--surface-3)',
}

export function Badge({
  tone = 'muted',
  children,
  className,
}: {
  tone?: keyof typeof tones
  children: ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
        tones[tone],
        className,
      )}
      style={{ background: backgrounds[tone] }}
    >
      {children}
    </span>
  )
}
