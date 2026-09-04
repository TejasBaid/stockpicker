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
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { useCurrentUser, useSignOut } from '@/hooks/useAuth'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/', label: 'Screener', icon: Filter, end: true },
  { to: '/strategies', label: 'Strategies', icon: Beaker },
  { to: '/backtests', label: 'Backtests', icon: LineChart },
  { to: '/portfolio', label: 'Portfolio', icon: Briefcase },
  { to: '/watchlist', label: 'Watchlist', icon: Star },
  { to: '/data', label: 'Data health', icon: BarChart3 },
]

function useTheme() {
  const [dark, setDark] = useState(
    () => localStorage.getItem('theme') !== 'light',
  )
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    localStorage.setItem('theme', dark ? 'dark' : 'light')
  }, [dark])
  return [dark, () => setDark((d) => !d)] as const
}

export function AppShell() {
  const { data: user } = useCurrentUser()
  const signOut = useSignOut()
  const navigate = useNavigate()
  const [dark, toggleTheme] = useTheme()

  return (
    <div className="flex h-full">
      <aside className="surface flex w-56 shrink-0 flex-col border-r">
        <div className="flex h-14 items-center gap-2.5 border-b px-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-[var(--accent)] text-[var(--accent-fg)]">
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M3 17l5-5 4 3 8-8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <span className="text-sm font-semibold tracking-tight">Screener</span>
        </div>

        <nav className="flex-1 space-y-0.5 p-2">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors',
                  isActive
                    ? 'surface-2 font-medium text-[var(--text)]'
                    : 'text-muted hover:surface-2 hover:text-[var(--text)]',
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="space-y-2 border-t p-3">
          <div className="flex items-center justify-between">
            <div className="min-w-0">
              <p className="truncate text-xs font-medium">{user?.display_name}</p>
              <p className="text-muted truncate text-xs">{user?.email}</p>
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

      <main className="min-w-0 flex-1 overflow-y-auto">
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
    <div className="flex items-start justify-between gap-4 border-b px-6 py-5">
      <div className="space-y-1">
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {description ? <p className="text-muted text-sm">{description}</p> : null}
      </div>
      {action}
    </div>
  )
}
