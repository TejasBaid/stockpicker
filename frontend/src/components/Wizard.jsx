import { useEffect, useState } from 'react'
import { api } from '../api'
import RegimeBanner from './RegimeBanner'
import PortfolioTable from './PortfolioTable'

const HORIZONS = [
  { key: 'short', label: 'Near-term', sub: '6–18 months', desc: 'Leans on momentum & low-volatility — price-driven signals that play out within a couple quarters.' },
  { key: 'medium', label: 'Medium-term', sub: '2–4 years', desc: 'Balanced blend of all five factors — the default all-weather mix.' },
  { key: 'long', label: 'Long-term', sub: '4+ years', desc: 'Leans on quality, growth & value — fundamentals that need years to fully compound.' },
]

const RISK_PROFILES = [
  { key: 'conservative', label: 'Conservative', desc: 'Tighter sector caps, higher liquidity bar, uptrend required, tilts toward low-volatility names.' },
  { key: 'balanced', label: 'Balanced', desc: 'Standard diversification and liquidity screening.' },
  { key: 'aggressive', label: 'Aggressive', desc: 'Wider sector exposure, lower liquidity bar, uptrend not required, tilts away from low-volatility.' },
]

function computeWeights(horizonWeights, riskProfiles, horizon, risk) {
  const base = { ...(horizonWeights?.[horizon] || {}) }
  const boost = riskProfiles?.[risk]?.low_vol_boost || 0
  base.low_vol = Math.max(0.02, (base.low_vol || 0) + boost)
  const sum = Object.values(base).reduce((a, b) => a + b, 0) || 1
  Object.keys(base).forEach((k) => { base[k] = base[k] / sum })
  return base
}

export default function Wizard() {
  const [step, setStep] = useState(0)
  const [horizon, setHorizon] = useState('medium')
  const [risk, setRisk] = useState('balanced')
  const [sectors, setSectors] = useState([])
  const [selectedSectors, setSelectedSectors] = useState([])
  const [capital, setCapital] = useState(200000)
  const [topN, setTopN] = useState(10)
  const [cfg, setCfg] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  useEffect(() => {
    api.config().then(setCfg).catch(() => {})
    api.sectors().then((r) => setSectors(r.sectors || [])).catch(() => {})
  }, [])

  const toggleSector = (s) => {
    setSelectedSectors((prev) => prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s])
  }

  const steps = ['Horizon', 'Risk profile', 'Sectors', 'Capital', 'Review']

  const runWizard = async () => {
    setRunning(true)
    setError(null)
    setResult(null)
    try {
      const weights = computeWeights(cfg?.horizon_weights, cfg?.risk_profiles, horizon, risk)
      const riskCfg = cfg?.risk_profiles?.[risk] || {}
      const r = await api.screen({
        capital,
        top_n: topN,
        weights,
        max_per_sector: riskCfg.max_per_sector ?? 3,
        min_liquidity_cr: riskCfg.min_liquidity_cr ?? 5,
        require_uptrend: riskCfg.require_uptrend ?? true,
        sectors: selectedSectors.length ? selectedSectors : null,
      })
      setResult(r)
      setStep(steps.length)
    } catch (e) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  const restart = () => {
    setStep(0)
    setResult(null)
    setError(null)
  }

  if (result) {
    return (
      <div className="wizard-result">
        <div className="panel wizard-summary">
          <h2>Your picks are ready</h2>
          <p className="panel-hint">
            {HORIZONS.find((h) => h.key === horizon)?.label} horizon · {RISK_PROFILES.find((r) => r.key === risk)?.label} risk
            {selectedSectors.length ? ` · ${selectedSectors.join(', ')}` : ' · All sectors'}
          </p>
          <button className="btn-secondary btn-small" onClick={restart}>Start over</button>
        </div>
        <RegimeBanner regime={result.regime} />
        <PortfolioTable result={result} onExport={() => {}} />
      </div>
    )
  }

  return (
    <div className="panel wizard">
      <h2>Pick Wizard</h2>
      <p className="panel-hint">Answer a few questions and get a ranked portfolio tailored to your sector interests, time horizon and risk appetite.</p>

      <div className="wizard-steps">
        {steps.map((s, i) => (
          <div key={s} className={`wizard-step-dot ${i === step ? 'active' : ''} ${i < step ? 'done' : ''}`}>
            <span className="dot-num">{i + 1}</span>
            <span className="dot-label">{s}</span>
          </div>
        ))}
      </div>

      {error && <div className="error-banner">{error}</div>}

      {step === 0 && (
        <div className="wizard-panel">
          <h3>What's your investment horizon?</h3>
          <div className="option-cards">
            {HORIZONS.map((h) => (
              <button key={h.key} className={`option-card ${horizon === h.key ? 'selected' : ''}`} onClick={() => setHorizon(h.key)}>
                <div className="option-card-title">{h.label}</div>
                <div className="option-card-sub">{h.sub}</div>
                <div className="option-card-desc">{h.desc}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      {step === 1 && (
        <div className="wizard-panel">
          <h3>What's your risk appetite?</h3>
          <div className="option-cards">
            {RISK_PROFILES.map((r) => (
              <button key={r.key} className={`option-card ${risk === r.key ? 'selected' : ''}`} onClick={() => setRisk(r.key)}>
                <div className="option-card-title">{r.label}</div>
                <div className="option-card-desc">{r.desc}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="wizard-panel">
          <h3>Any sectors you want to focus on?</h3>
          <p className="panel-hint">Leave everything unselected to screen the full universe.</p>
          <div className="sector-chips">
            {sectors.map((s) => (
              <button
                key={s.sector}
                className={`sector-chip ${selectedSectors.includes(s.sector) ? 'selected' : ''}`}
                onClick={() => toggleSector(s.sector)}
              >
                {s.sector} <span className="dim">({s.count})</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="wizard-panel">
          <h3>Capital &amp; portfolio size</h3>
          <div className="field-row">
            <label>
              Capital (₹)
              <input type="number" min="1000" step="1000" value={capital} onChange={(e) => setCapital(Number(e.target.value))} />
            </label>
            <label>
              Number of picks
              <input type="number" min="3" max="30" value={topN} onChange={(e) => setTopN(Number(e.target.value))} />
            </label>
          </div>
        </div>
      )}

      {step === 4 && (
        <div className="wizard-panel">
          <h3>Review</h3>
          <div className="review-grid">
            <div><span className="metric-label">Horizon</span><div className="metric-value">{HORIZONS.find((h) => h.key === horizon)?.label}</div></div>
            <div><span className="metric-label">Risk profile</span><div className="metric-value">{RISK_PROFILES.find((r) => r.key === risk)?.label}</div></div>
            <div><span className="metric-label">Sectors</span><div className="metric-value">{selectedSectors.length ? selectedSectors.join(', ') : 'All'}</div></div>
            <div><span className="metric-label">Capital</span><div className="metric-value">₹{capital.toLocaleString('en-IN')}</div></div>
            <div><span className="metric-label">Picks</span><div className="metric-value">{topN}</div></div>
          </div>
        </div>
      )}

      <div className="wizard-nav">
        <button className="btn-secondary" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0}>Back</button>
        {step < steps.length - 1 && (
          <button className="btn-primary" onClick={() => setStep((s) => s + 1)}>Next</button>
        )}
        {step === steps.length - 1 && (
          <button className="btn-primary" onClick={runWizard} disabled={running}>
            {running ? 'Building portfolio…' : 'Generate my picks'}
          </button>
        )}
      </div>
    </div>
  )
}
