import {
  BarChart3,
  Beaker,
  Briefcase,
  Filter,
  LineChart,
  LogOut,
  Moon,
  Star,
  Sun,
  Wallet,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { useCurrentUser, useSignOut } from '@/hooks/useAuth'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/', label: 'Screener', icon: Filter, end: true },
  { to: '/plan', label: 'Plan', icon: Wallet },
  { to: '/strategies', label: 'Strategies', icon: Beaker },
  { to: '/backtests', label: 'Backtests', icon: LineChart },
  { to: '/portfolio', label: 'Portfolio', icon: Briefcase },
  { to: '/watchlist', label: 'Watchlist', icon: Star },
  { to: '/data', label: 'Data health', icon: BarChart3 },
]

function useTheme() {
  const [dark, setDark] = useState(() => localStorage.getItem('theme') !== 'light')
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    localStorage.setItem('theme', dark ? 'dark' : 'light')
  }, [dark])
  return [dark, () => setDark((d) => !d)] as const
}

export function Logo({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        'flex items-center justify-center rounded-xl text-[var(--accent-fg)]',
        className,
      )}
      style={{
        background: 'linear-gradient(135deg, var(--accent), color-mix(in oklab, var(--accent) 60%, #b9a7ff))',
      }}
    >
      <svg viewBox="0 0 24 24" className="h-1/2 w-1/2" fill="none" stroke="currentColor" strokeWidth="2.5">
        <path d="M3 17l5-5 4 3 8-8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  )
}

export function AppShell() {
  const { data: user } = useCurrentUser()
  const signOut = useSignOut()
  const navigate = useNavigate()
  const [dark, toggleTheme] = useTheme()

  return (
    <div className="flex h-full p-2.5 gap-2.5">
      <aside className="surface rounded-card flex w-60 shrink-0 flex-col border">
        <div className="flex h-16 items-center gap-3 px-5">
          <Logo className="h-8 w-8" />
          <span className="text-[15px] font-semibold tracking-tight">Screener</span>
        </div>

        <nav className="flex-1 space-y-1 px-3 py-2">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  'relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors',
                  isActive
                    ? 'text-[var(--text)] font-medium'
                    : 'text-muted hover:surface-2 hover:text-[var(--text)]',
                )
              }
              style={({ isActive }) =>
                isActive ? { background: 'var(--accent-soft)' } : undefined
              }
            >
              {({ isActive }) => (
                <>
                  {isActive ? (
                    <span
                      className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full"
                      style={{ background: 'var(--accent)' }}
                    />
                  ) : null}
                  <Icon
                    className="h-[18px] w-[18px]"
                    style={isActive ? { color: 'var(--accent)' } : undefined}
                  />
                  {label}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="space-y-3 p-3">
          <div className="surface-2 flex items-center justify-between gap-2 rounded-xl p-3">
            <div className="min-w-0">
              <p className="truncate text-xs font-medium">{user?.display_name}</p>
              <p className="text-dim truncate text-xs">{user?.email}</p>
            </div>
            <Button variant="ghost" size="icon" onClick={toggleTheme} aria-label="Toggle theme">
              {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
          </div>
          <Button
            variant="secondary"
            size="sm"
            className="w-full"
            onClick={() => signOut.mutate(undefined, { onSuccess: () => navigate('/signin') })}
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign out
          </Button>
        </div>
      </aside>

      <main className="surface rounded-card min-w-0 flex-1 overflow-y-auto border">
        <Outlet />
      </main>
    </div>
  )
}

export function PageHeader({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex items-start justify-between gap-4 px-7 pb-5 pt-6">
      <div className="space-y-1.5">
        <h1 className="text-[22px] font-semibold tracking-tight">{title}</h1>
        {description ? (
          <p className="text-muted max-w-2xl text-sm leading-relaxed">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  )
}
