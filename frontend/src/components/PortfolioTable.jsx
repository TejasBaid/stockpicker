import { useState } from 'react'
import { api } from '../api'
import { FACTOR_INFO } from '../factorInfo'
import StockDetailPanel from './StockDetailPanel'

function zClass(v) {
  if (v == null) return ''
  if (v > 0.5) return 'z-pos'
  if (v < -0.5) return 'z-neg'
  return 'z-neu'
}

function fmt(v, digits = 2) {
  if (v == null) return '—'
  return Number(v).toLocaleString('en-IN', { maximumFractionDigits: digits })
}

export default function PortfolioTable({ result, onExport, strategy, factorMode, weights }) {
  const [selectedTicker, setSelectedTicker] = useState(null)
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  if (!result) return null
  const { portfolio, capital, effective_capital, total_deployed, cash_remaining, regime_cash_buffer, universe_size, gated_size, consensus } = result

  const isWeighted = !strategy || strategy.mode === 'weights'
  const compositeTooltip = isWeighted
    ? 'Blended score across all five factors using the selected strategy\'s weights.'
    : strategy.desc

  const openStock = async (ticker) => {
    setSelectedTicker(ticker)
    setDetail(null)
    setError(null)
    setLoading(true)
    try {
      const d = await api.stockDetail(ticker, { factorMode, weights: factorMode === 'all' ? weights : undefined })
      setDetail(d)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const closeModal = () => {
    setSelectedTicker(null)
    setDetail(null)
    setError(null)
  }

  return (
    <div className="panel">
      <div className="table-header">
        <h2>Selected Portfolio ({portfolio.length} stocks)</h2>
        <button className="btn-secondary" onClick={onExport}>Export CSV</button>
      </div>
      {consensus && (
        <div className="consensus-banner">
          Consensus of <b>{consensus.strategies_combined} strategies</b> — each contributed its top {consensus.candidate_pool_per_strategy} names;{' '}
          <b>{consensus.consensus_size}</b> stock{consensus.consensus_size === 1 ? '' : 's'} made every strategy's shortlist.
        </div>
      )}
      <div className="summary-strip">
        <span>Universe <b>{universe_size}</b></span>
        <span>Passed gates <b>{gated_size}</b></span>
        <span>Capital <b>₹{fmt(capital, 0)}</b></span>
        <span>Deployed <b>₹{fmt(total_deployed, 0)}</b></span>
        <span>Cash (uninvested) <b>₹{fmt(cash_remaining, 0)}</b></span>
        <span>Regime buffer <b>₹{fmt(regime_cash_buffer, 0)}</b></span>
      </div>
      <p className="panel-hint">Click a row to see its full factor breakdown and fundamentals.</p>
      {!isWeighted && (
        <p className="panel-hint strategy-columns-note">
          Mom/Qual/Growth/Value/LowVol below are always the <b>classic</b> factor breakdown, shown for comparison across strategies — they
          are not what {strategy?.label || 'this strategy'} actually ranks on. Hover <b>Composite</b> for what really drove this ranking.
        </p>
      )}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Ticker</th>
              <th>Name</th>
              <th>Sector</th>
              <th>Wt %</th>
              <th>Price</th>
              <th>Shares</th>
              <th>Cost</th>
              <th>Stop-Loss</th>
              {Object.entries(FACTOR_INFO).map(([key, info]) => (
                <th key={key} title={info.desc}>{info.short}</th>
              ))}
              <th title={compositeTooltip}>Composite</th>
            </tr>
          </thead>
          <tbody>
            {portfolio.map((row, i) => (
              <tr key={row.ticker} className="row-clickable" onClick={() => openStock(row.ticker)}>
                <td className="dim">{i + 1}</td>
                <td className="ticker">{row.ticker}</td>
                <td className="name-cell" title={row.name}>{row.name}</td>
                <td className="dim">{row.sector}</td>
                <td>{fmt(row.weight * 100, 1)}%</td>
                <td>₹{fmt(row.close_price)}</td>
                <td>{row.shares}</td>
                <td>₹{fmt(row.actual_cost, 0)}</td>
                <td className="dim">₹{fmt(row.stop_loss)}</td>
                <td className={zClass(row.momentum_z)}>{fmt(row.momentum_z)}</td>
                <td className={zClass(row.quality_z)}>{fmt(row.quality_z)}</td>
                <td className={zClass(row.growth_z)}>{fmt(row.growth_z)}</td>
                <td className={zClass(row.value_z)}>{fmt(row.value_z)}</td>
                <td className={zClass(row.low_vol_z)}>{fmt(row.low_vol_z)}</td>
                <td className={`composite ${zClass(row.composite)}`}>{fmt(row.composite)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selectedTicker && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={closeModal} aria-label="Close">×</button>
            {loading && <div className="empty-state">Loading {selectedTicker}…</div>}
            {error && <div className="error-banner">{error}</div>}
            {detail && !loading && <StockDetailPanel detail={detail} compositeNote={compositeTooltip} />}
          </div>
        </div>
      )}
    </div>
  )
}
