import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { Spinner } from '@/components/ui/spinner'
import { useCurrentUser } from '@/hooks/useAuth'
import Backtests from '@/routes/Backtests'
import DataHealth from '@/routes/DataHealth'
import Plan from '@/routes/Plan'
import PortfolioPage from '@/routes/PortfolioPage'
import Strategies from '@/routes/Strategies'
import WatchlistPage from '@/routes/WatchlistPage'
import Screener from '@/routes/Screener'
import SignIn from '@/routes/SignIn'
import SignUp from '@/routes/SignUp'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { data: user, isPending, isError } = useCurrentUser()

  if (isPending) {
    return (
      <div className="text-muted flex h-full flex-col items-center justify-center gap-3 text-sm">
        <Spinner className="h-5 w-5" />
        <p>Waking the server…</p>
        <p className="text-xs">The free tier sleeps when idle; this can take up to a minute.</p>
      </div>
    )
  }
  if (isError || !user) return <Navigate to="/signin" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/signin" element={<SignIn />} />
      <Route path="/signup" element={<SignUp />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Screener />} />
        <Route path="plan" element={<Plan />} />
        <Route path="strategies" element={<Strategies />} />
        <Route path="backtests" element={<Backtests />} />
        <Route path="portfolio" element={<PortfolioPage />} />
        <Route path="watchlist" element={<WatchlistPage />} />
        <Route path="data" element={<DataHealth />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
