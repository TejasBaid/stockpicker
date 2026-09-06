import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function Field({
  label,
  htmlFor,
  hint,
  error,
  children,
  className,
}: {
  label: string
  htmlFor: string
  hint?: string
  error?: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn('space-y-2', className)}>
      <label htmlFor={htmlFor} className="text-muted block text-xs font-medium">
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-neg text-xs">{error}</p>
      ) : hint ? (
        <p className="text-dim text-xs leading-relaxed">{hint}</p>
      ) : null}
    </div>
  )
}
