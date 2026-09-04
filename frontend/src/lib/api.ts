/**
 * API client.
 *
 * Requests are same-origin (Vite proxies /api in dev), so the httpOnly session
 * cookie is sent automatically and no token is ever held in JavaScript.
 *
 * The backend runs on Render's free tier and sleeps when idle, so the first
 * request after a quiet period can take ~50s to wake it. `ApiError.isColdStart`
 * lets the UI say "waking the server" instead of looking broken.
 */

const BASE = import.meta.env.VITE_API_URL ?? ''
const WAKE_TIMEOUT_MS = 75_000

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly isColdStart = false,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), WAKE_TIMEOUT_MS)

  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      signal: controller.signal,
      credentials: 'include',
      headers: {
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
    })
  } catch (err) {
    clearTimeout(timer)
    const aborted = err instanceof DOMException && err.name === 'AbortError'
    throw new ApiError(0, aborted ? 'The server took too long to wake up.' : 'Network error.', true)
  }
  clearTimeout(timer)

  if (res.status === 204) return undefined as T

  const body = await res.json().catch(() => null)
  if (!res.ok) {
    const detail =
      (body && typeof body.detail === 'string' && body.detail) || `Request failed (${res.status})`
    throw new ApiError(res.status, detail)
  }
  return body as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined }),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

export interface User {
  id: string
  email: string
  display_name: string
  is_admin: boolean
}

export interface Health {
  status: 'ok' | 'degraded'
  database: boolean
}

export const authApi = {
  me: () => api.get<User>('/api/v1/auth/me'),
  signIn: (email: string, password: string) =>
    api.post<User>('/api/v1/auth/signin', { email, password }),
  signUp: (payload: {
    invite_code: string
    email: string
    display_name: string
    password: string
  }) => api.post<User>('/api/v1/auth/signup', payload),
  signOut: () => api.post<void>('/api/v1/auth/signout'),
  createInvite: (label: string, ttl_days = 14) =>
    api.post<{ code: string; expires_in_days: number }>('/api/v1/auth/invites', { label, ttl_days }),
}

export const opsApi = {
  health: () => api.get<Health>('/health'),
}

export interface Dataset {
  key: string
  label: string
  symbols: number
  rows: number
  coverage_pct: number
  latest: string | null
  source: string
  note: string | null
}

export interface IngestRun {
  id: string
  job: string
  status: string
  started_at: string
  finished_at: string | null
  duration_seconds: number | null
  rows_written: number
  symbols_processed: number
  symbols_failed: number
  api_calls: number
  error: string | null
  details: Record<string, unknown>
}

export interface DataOverview {
  universe_size: number
  instruments: number
  latest_bar_date: string | null
  bars_stale_days: number | null
  datasets: Dataset[]
  point_in_time: {
    total_rows: number
    exact_rows: number
    estimated_rows: number
    exact_pct: number
  }
  provider_usage: {
    history: { provider: string; date: string; calls: number; errors: number }[]
    indian_api: {
      used_today: number
      daily_budget: number
      remaining: number
      pct_used: number
    }
  }
  recent_runs: IngestRun[]
}

export const dataApi = {
  overview: () => api.get<DataOverview>('/api/v1/data/overview'),
  runs: (limit = 30) => api.get<IngestRun[]>(`/api/v1/data/runs?limit=${limit}`),
}

export interface FactorMeta {
  name: string
  label: string
  description: string
  unit: string
  higher_is_better: boolean
  sector_neutral: boolean
}

export interface Preset {
  slug: string
  name: string
  description: string
  weights: Record<string, number>
  filters: { factor: string; op: string; value: number }[]
}

export interface ScreenResult {
  rank: number
  symbol: string
  name: string | null
  sector: string | null
  composite: number
  contributions: Record<string, number>
  factors: Record<string, { raw: number | null; decile: number | null }>
}

export interface ScreenResponse {
  as_of: string
  universe: string
  universe_size: number
  eligible: number
  returned: number
  basis: string
  weights: Record<string, number>
  coverage: Record<string, number>
  results: ScreenResult[]
}

export const screenerApi = {
  factors: () =>
    api.get<{ categories: Record<string, FactorMeta[]>; count: number }>(
      '/api/v1/screener/factors',
    ),
  presets: () => api.get<{ presets: Preset[] }>('/api/v1/screener/presets'),
  run: (body: {
    weights: Record<string, number>
    filters?: { factor: string; op: string; value: number }[]
    limit?: number
    max_per_sector?: number | null
    basis?: string
  }) => api.post<ScreenResponse>('/api/v1/screener/run', body),
}

export interface BacktestMetrics {
  total_return_pct: number
  cagr_pct: number
  volatility_pct: number
  sharpe: number | null
  sortino: number | null
  max_drawdown_pct: number
  calmar: number | null
  positive_days_pct: number
  benchmark_cagr_pct?: number
  benchmark_max_drawdown_pct?: number
  alpha_pct?: number
  universe_cagr_pct?: number
  universe_max_drawdown_pct?: number
  alpha_vs_universe_pct?: number
  beta?: number
  information_ratio?: number
  total_costs: number
  cost_drag_pct: number
  trades: number
  rebalances: number
}

export interface CurvePoint {
  date: string
  value: number
}

export interface BacktestResult {
  start: string
  end: string
  frequency: string
  holdings: number
  initial_capital: number
  final_value: number
  metrics: BacktestMetrics
  equity_curve: CurvePoint[]
  benchmark_curve: CurvePoint[]
  universe_curve: CurvePoint[]
  monthly_returns: { month: string; return_pct: number }[]
  rebalance_log: { date: string; holdings: string[]; count: number }[]
}

export interface BacktestJob {
  id: string
  status: 'queued' | 'running' | 'done' | 'failed'
  progress: number
  error: string | null
  created_at: string
  finished_at: string | null
  params: Record<string, unknown>
  result?: BacktestResult | null
}

export const backtestApi = {
  enqueue: (body: Record<string, unknown>) => api.post<BacktestJob>('/api/v1/backtests', body),
  list: () => api.get<BacktestJob[]>('/api/v1/backtests'),
  get: (id: string) => api.get<BacktestJob>(`/api/v1/backtests/${id}`),
}

export interface PortfolioSummary {
  id: string
  name: string
  description: string | null
  cash: number
  positions: number
  invested: number
  market_value: number
  total_value: number
  pnl: number
  pnl_pct: number
}

export interface FactorDrift {
  factor: string
  entry_decile: number
  current_decile: number
  drift: number
}

export interface Holding {
  id: string
  symbol: string
  name: string | null
  sector: string | null
  quantity: number
  avg_price: number
  last_price: number
  invested: number
  market_value: number
  pnl: number
  pnl_pct: number
  weight_pct: number
  opened_on: string
  held_days: number
  tax_status: 'long-term' | 'short-term'
  days_to_long_term: number
  thesis: string | null
  conviction: string | null
  exit_plan: {
    stop_type: string | null
    stop_price: number | null
    stop_distance_pct: number | null
    target_ladder: { price: number; pct: number }[] | null
    time_stop_on: string | null
    triggers: string[]
    notes: string | null
  } | null
  factor_drift: FactorDrift[]
}

export interface PortfolioDetail extends PortfolioSummary {
  holdings: Holding[]
  tax: {
    short_term_gain: number
    long_term_gain: number
    estimated_tax: number
    ltcg_exemption_used: number
    note: string
  }
}

export interface PortfolioAlert {
  symbol: string
  kind: 'exit' | 'factor_decay' | 'tax'
  message: string
}

export const portfolioApi = {
  list: () => api.get<PortfolioSummary[]>('/api/v1/portfolios'),
  create: (body: { name: string; description?: string; cash?: number }) =>
    api.post<PortfolioSummary>('/api/v1/portfolios', body),
  get: (id: string) => api.get<PortfolioDetail>(`/api/v1/portfolios/${id}`),
  alerts: (id: string) => api.get<PortfolioAlert[]>(`/api/v1/portfolios/${id}/alerts`),
  addPosition: (
    id: string,
    body: {
      symbol: string
      quantity: number
      avg_price: number
      opened_on: string
      thesis?: string
      conviction?: string
    },
  ) => api.post<{ id: string }>(`/api/v1/portfolios/${id}/positions`, body),
  removePosition: (id: string, positionId: string) =>
    api.del<void>(`/api/v1/portfolios/${id}/positions/${positionId}`),
  setExitPlan: (
    id: string,
    positionId: string,
    body: Record<string, unknown>,
  ) => api.put<{ ok: boolean }>(`/api/v1/portfolios/${id}/positions/${positionId}/exit-plan`, body),
  stopSuggestion: (id: string, symbol: string) =>
    api.get<{ price: number; atr: number; stop: number; stop_distance_pct: number }>(
      `/api/v1/portfolios/${id}/stop-suggestion/${symbol}`,
    ),
  searchInstruments: (q: string) =>
    api.get<{ symbol: string; name: string }[]>(
      `/api/v1/portfolios/_search/instruments?q=${encodeURIComponent(q)}`,
    ),
}
