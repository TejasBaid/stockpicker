import type { InputHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        'surface-2 flex h-10 w-full rounded-xl border px-3.5 py-1 text-sm transition-colors',
        'placeholder:text-[var(--text-dim)]',
        'focus-visible:outline-none focus-visible:border-[var(--accent)]',
        'focus-visible:ring-2 focus-visible:ring-[var(--accent-soft)]',
        'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    />
  )
}
