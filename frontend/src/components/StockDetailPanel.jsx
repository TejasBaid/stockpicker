import { FACTOR_INFO } from '../factorInfo'

function fmt(v, digits = 2) {
  if (v == null) return '—'
  return Number(v).toLocaleString('en-IN', { maximumFractionDigits: digits })
}

function pct(v, digits = 1) {
  if (v == null) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

function zBar(v) {
  const clamped = Math.max(-3, Math.min(3, v ?? 0))
  const pctWidth = (Math.abs(clamped) / 3) * 50
  const positive = clamped >= 0
  return { pctWidth, positive }
}

function week52Position(close, low, high) {
  if (close == null || low == null || high == null || high <= low) return null
  return Math.min(100, Math.max(0, ((close - low) / (high - low)) * 100))
}

export default function StockDetailPanel({ detail, compositeNote }) {
  const w52pos = week52Position(detail.close_price, detail.week52_low, detail.week52_high)
  const sortedStrategyScores = detail.strategy_scores
    ? [...detail.strategy_scores].sort((a, b) => a.rank - b.rank)
    : null

  return (
    <>
      <div className="stock-detail-header">
        <div>
          <h2>{detail.ticker} <span className="dim">· {detail.sector}</span></h2>
          <p className="panel-hint">{detail.name}</p>
        </div>
        <div className="stock-price-block">
          <div className="stock-price">₹{fmt(detail.close_price)}</div>
          <div className="dim">Stop-loss ₹{fmt(detail.stop_loss)}</div>
        </div>
      </div>

      {w52pos != null && (
        <div className="week52-row">
          <span className="week52-label">52W Low ₹{fmt(detail.week52_low)}</span>
          <div className="week52-track">
            <div className="week52-marker" style={{ left: `${w52pos}%` }} />
          </div>
          <span className="week52-label">52W High ₹{fmt(detail.week52_high)}</span>
        </div>
      )}

      <div className="summary-strip">
        <span>Composite rank <b>#{detail.rank_of_universe} / {detail.universe_size}</b></span>
        <span>Liquidity <b>₹{fmt(detail.liquidity_cr)} Cr/day</b></span>
        <span>Trend gate <b className={detail.above_200sma ? 'good' : 'bad'}>{detail.above_200sma ? 'Above 200-SMA' : 'Below 200-SMA'}</b></span>
      </div>

      <h3>Factor Scores (z-scores, -3 to +3)</h3>
      <div className="factor-scores">
        {Object.entries(FACTOR_INFO).map(([key, info]) => {
          const v = detail.scores[key]
          const { pctWidth, positive } = zBar(v)
          return (
            <div className="factor-score-row" key={key}>
              <div className="factor-score-label-block">
                <span className="factor-score-label">{info.label}</span>
                <span className="factor-score-desc">{info.desc}</span>
              </div>
              <div className="factor-score-track">
                <div className="factor-score-mid" />
                <div
                  className={`factor-score-fill ${positive ? 'pos' : 'neg'}`}
                  style={{ width: `${pctWidth}%`, [positive ? 'left' : 'right']: '50%' }}
                />
              </div>
              <span className="factor-score-value">{fmt(v)}</span>
            </div>
          )
        })}
        <div className="factor-score-row composite-row">
          <div className="factor-score-label-block">
            <span className="factor-score-label">Composite</span>
            <span className="factor-score-desc">
              {compositeNote || 'Blended score across all five factors using the selected strategy\'s weights.'}
            </span>
          </div>
          <div className="factor-score-track">
            <div className="factor-score-mid" />
            <div
              className={`factor-score-fill ${zBar(detail.scores.composite).positive ? 'pos' : 'neg'}`}
              style={{
                width: `${zBar(detail.scores.composite).pctWidth}%`,
                [zBar(detail.scores.composite).positive ? 'left' : 'right']: '50%',
              }}
            />
          </div>
          <span className="factor-score-value">{fmt(detail.scores.composite)}</span>
        </div>
      </div>

      <h3>Fundamentals</h3>
      <div className="fundamentals-grid">
        <Stat label="P/E" value={fmt(detail.fundamentals.pe)} />
        <Stat label="P/B" value={fmt(detail.fundamentals.pb)} />
        <Stat label="ROE" value={pct(detail.fundamentals.roe)} />
        <Stat label="Debt/Equity" value={fmt(detail.fundamentals.debt_equity)} />
        <Stat label="Revenue Growth" value={pct(detail.fundamentals.revenue_growth)} />
        <Stat label="Earnings Growth" value={pct(detail.fundamentals.earnings_growth)} />
        <Stat label="Profit Margin" value={pct(detail.fundamentals.profit_margin)} />
        <Stat label="Market Cap" value={detail.fundamentals.market_cap ? `₹${fmt(detail.fundamentals.market_cap / 1e7, 0)} Cr` : '—'} />
      </div>

      {sortedStrategyScores && (
        <>
          <h3>Composite Score by Strategy</h3>
          <p className="panel-hint strategy-scores-hint">How this stock ranks under every strategy, best rank first.</p>
          <div className="strategy-scores-table">
            {sortedStrategyScores.map((s) => (
              <div className="strategy-scores-row" key={s.key}>
                <span className="strategy-scores-label">{s.label}</span>
                <span className={`strategy-scores-composite ${zClass(s.composite)}`}>{fmt(s.composite)}</span>
                <span className="strategy-scores-rank dim">#{s.rank} / {s.universe_size}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </>
  )
}

function zClass(v) {
  if (v == null) return ''
  if (v > 0.5) return 'z-pos'
  if (v < -0.5) return 'z-neg'
  return 'z-neu'
}

function Stat({ label, value }) {
  return (
    <div className="stat-tile">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
    </div>
  )
}
