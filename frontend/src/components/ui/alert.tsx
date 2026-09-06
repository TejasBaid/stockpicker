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
  const color =
    tone === 'error' ? 'var(--neg)' : tone === 'success' ? 'var(--pos)' : 'var(--text-muted)'
  const background =
    tone === 'error' ? 'var(--neg-soft)' : tone === 'success' ? 'var(--pos-soft)' : 'var(--surface-2)'
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      className={cn('rounded-card flex gap-3 border px-4 py-3 text-sm', className)}
      style={{ background, borderColor: tone === 'info' ? 'var(--border)' : color }}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" style={{ color }} />
      <div className="min-w-0" style={{ color: tone === 'info' ? 'var(--text)' : color }}>
        {children}
      </div>
    </div>
  )
}
