import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

const tones = {
  ok: 'text-pos border-[var(--pos)]/40 bg-[var(--pos)]/10',
  fail: 'text-neg border-[var(--neg)]/40 bg-[var(--neg)]/10',
  warn: 'text-[var(--warn)] border-[var(--warn)]/40 bg-[var(--warn)]/10',
  muted: 'text-muted',
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
        'inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium',
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}
