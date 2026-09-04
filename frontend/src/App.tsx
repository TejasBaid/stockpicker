import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { Spinner } from '@/components/ui/spinner'
import { useCurrentUser } from '@/hooks/useAuth'
import DataHealth from '@/routes/DataHealth'
import Screener from '@/routes/Screener'
import { Placeholder } from '@/routes/Placeholder'
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
        <Route
          path="strategies"
          element={
            <Placeholder
              title="Strategies"
              description="Build, save and version your own multi-factor strategies."
              phase="phase 3"
            />
          }
        />
        <Route
          path="backtests"
          element={
            <Placeholder
              title="Backtests"
              description="Point-in-time walk-forward tests with Indian transaction costs."
              phase="phase 3"
            />
          }
        />
        <Route
          path="portfolio"
          element={
            <Placeholder
              title="Portfolio"
              description="Track positions, plan exits and review theses."
              phase="phase 4"
            />
          }
        />
        <Route
          path="watchlist"
          element={
            <Placeholder title="Watchlist" description="Names you're tracking." phase="phase 4" />
          }
        />
        <Route path="data" element={<DataHealth />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
