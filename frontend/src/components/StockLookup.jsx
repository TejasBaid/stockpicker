import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import StockDetailPanel from './StockDetailPanel'

export default function StockLookup({ ready }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const debounceRef = useRef(null)

  useEffect(() => {
    if (!ready) return
    clearTimeout(debounceRef.current)
    if (!query.trim()) {
      setResults([])
      return
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const r = await api.stockSearch(query.trim())
        setResults(r.results || [])
      } catch (e) {
        setResults([])
      }
    }, 250)
    return () => clearTimeout(debounceRef.current)
  }, [query, ready])

  const selectStock = async (ticker) => {
    setSelected(ticker)
    setResults([])
    setQuery(ticker)
    setLoading(true)
    setError(null)
    try {
      const d = await api.stockDetail(ticker)
      setDetail(d)
    } catch (e) {
      setError(e.message)
      setDetail(null)
    } finally {
      setLoading(false)
    }
  }

  if (!ready) {
    return (
      <div className="panel empty-state">
        <p>Refresh market data first to look up individual stocks.</p>
      </div>
    )
  }

  return (
    <div className="lookup-layout">
      <div className="panel search-panel">
        <h2>Stock Lookup</h2>
        <p className="panel-hint">Search any stock in the universe to see its full factor breakdown, fundamentals and risk gates.</p>
        <div className="search-box">
          <input
            type="text"
            placeholder="Search by ticker or company name…"
            value={query}
            onChange={(e) => { setQuery(e.target.value); setSelected(null) }}
            autoFocus
          />
          {results.length > 0 && (
            <div className="search-results">
              {results.map((r) => (
                <button key={r.ticker} className="search-result-row" onClick={() => selectStock(r.ticker)}>
                  <span className="ticker">{r.ticker}</span>
                  <span className="name-cell">{r.name}</span>
                  <span className="dim">{r.sector}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {loading && <div className="panel empty-state">Loading {selected}…</div>}
      {error && <div className="error-banner">{error}</div>}

      {detail && !loading && (
        <div className="panel stock-detail">
          <StockDetailPanel detail={detail} />
        </div>
      )}

      {!detail && !loading && !error && (
        <div className="panel empty-state">
          <p>Search for a stock above to see its momentum, quality, growth, value and low-volatility scores, plus liquidity and trend gates.</p>
        </div>
      )}
    </div>
  )
}
