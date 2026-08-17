const BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

async function request(path, options) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

export const api = {
  status: () => request('/api/status'),
  refresh: () => request('/api/refresh', { method: 'POST' }),
  regime: () => request('/api/regime'),
  screen: (body) => request('/api/screen', { method: 'POST', body: JSON.stringify(body) }),
  config: () => request('/api/config'),
  sectors: () => request('/api/sectors'),
  stockSearch: (q) => request(`/api/stock-search?q=${encodeURIComponent(q)}`),
  stockDetail: (ticker, { factorMode, weights } = {}) => {
    const qs = new URLSearchParams()
    if (factorMode) qs.set('factor_mode', factorMode)
    if (weights) qs.set('weights', JSON.stringify(weights))
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return request(`/api/stock/${encodeURIComponent(ticker)}${suffix}`)
  },
}
