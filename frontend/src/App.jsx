import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import DataStatus from './components/DataStatus'
import RegimeBanner from './components/RegimeBanner'
import Controls from './components/Controls'
import PortfolioTable from './components/PortfolioTable'
import StockLookup from './components/StockLookup'
import Wizard from './components/Wizard'

const DEFAULT_PARAMS = {
  capital: 200000,
  top_n: 10,
  max_per_sector: 3,
  min_liquidity_cr: 5,
  require_uptrend: true,
  weights: { momentum: 0.3, quality: 0.2, growth: 0.15, value: 0.15, low_vol: 0.2 },
  strategy_key: 'balanced',
  factor_mode: 'all',
}

const TABS = [
  { key: 'screener', label: 'Screener' },
  { key: 'lookup', label: 'Stock Lookup' },
  { key: 'wizard', label: 'Pick Wizard' },
]

export default function App() {
  const [tab, setTab] = useState('screener')
  const [status, setStatus] = useState(null)
  const [cfg, setCfg] = useState(null)
  const [params, setParams] = useState(DEFAULT_PARAMS)
  const [result, setResult] = useState(null)
  const [running, setRunning] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)
  const pollRef = useRef(null)

  const loadStatus = async () => {
    try {
      const s = await api.status()
      setStatus(s)
      return s
    } catch (e) {
      setStatus(null)
      return null
    }
  }

  useEffect(() => {
    api.config().then((c) => {
      setCfg(c)
      setParams((p) => ({
        ...p,
        capital: c.default_capital,
        top_n: c.default_top_n,
        max_per_sector: c.default_max_per_sector,
        min_liquidity_cr: c.default_min_liquidity_cr,
        weights: c.default_weights,
      }))
    }).catch(() => {})
    loadStatus()
    return () => clearInterval(pollRef.current)
  }, [])

  const handleRefresh = async () => {
    setRefreshing(true)
    setError(null)
    await api.refresh().catch((e) => setError(e.message))
    pollRef.current = setInterval(async () => {
      const s = await loadStatus()
      if (s && !s.refreshing) {
        clearInterval(pollRef.current)
        setRefreshing(false)
      }
    }, 1500)
  }

  const handleRun = async () => {
    setRunning(true)
    setError(null)
    try {
      const r = await api.screen(params)
      setResult(r)
    } catch (e) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  const handleExport = () => {
    if (!result) return
    const cols = ['ticker', 'name', 'sector', 'weight', 'close_price', 'shares', 'actual_cost',
      'stop_loss', 'momentum_z', 'quality_z', 'growth_z', 'value_z', 'low_vol_z', 'composite']
    const lines = [cols.join(',')]
    for (const row of result.portfolio) {
      lines.push(cols.map((c) => JSON.stringify(row[c] ?? '')).join(','))
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `screener_portfolio_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>Nifty Multi-Factor Screener</h1>
          <p className="subtitle">Momentum · Quality · Growth · Value · Low-Volatility — with regime, liquidity &amp; diversification gates</p>
        </div>
        <DataStatus status={status} onRefresh={handleRefresh} refreshing={refreshing} />
      </header>

      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.key} className={`tab ${tab === t.key ? 'active' : ''}`} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </nav>

      {error && <div className="error-banner">{error}</div>}

      {!status?.ready && !refreshing && (
        <div className="panel empty-state">
          <p>No market data cached yet. Click <b>Refresh Market Data</b> to pull the Nifty 200 universe (takes ~30–60s).</p>
        </div>
      )}

      {tab === 'screener' && (
        <div className="layout">
          <Controls
            params={params}
            cfg={cfg}
            onChange={setParams}
            onRun={handleRun}
            running={running}
          />

          <div className="results-col">
            {result && <RegimeBanner regime={result.regime} />}
            {result && (
              <PortfolioTable
                result={result}
                onExport={handleExport}
                strategy={cfg?.strategies?.[params.strategy_key]}
                factorMode={params.factor_mode}
                weights={params.weights}
              />
            )}
            {!result && status?.ready && (
              <div className="panel empty-state">
                <p>Set your parameters and click <b>Run Screener</b> to generate a ranked, risk-sized portfolio.</p>
              </div>
            )}
          </div>
        </div>
      )}

      {tab === 'lookup' && <StockLookup ready={status?.ready} />}

      {tab === 'wizard' && status?.ready && <Wizard />}
      {tab === 'wizard' && !status?.ready && (
        <div className="panel empty-state">
          <p>Refresh market data first to use the Pick Wizard.</p>
        </div>
      )}
    </div>
  )
}
