import { AlertCircle, CheckCircle2, Info } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

const icons = { error: AlertCircle, success: CheckCircle2, info: Info }

export function Alert({
  tone = 'info',
  children,
  className,
}: {
  tone?: 'error' | 'success' | 'info'
  children: ReactNode
  className?: string
}) {
  const Icon = icons[tone]
  const toneClass =
    tone === 'error'
      ? 'text-neg border-[var(--neg)]/40'
      : tone === 'success'
        ? 'text-pos border-[var(--pos)]/40'
        : 'text-muted'
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      className={cn('surface-2 flex gap-2.5 rounded-md border px-3 py-2.5 text-sm', toneClass, className)}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0">{children}</div>
    </div>
  )
}
