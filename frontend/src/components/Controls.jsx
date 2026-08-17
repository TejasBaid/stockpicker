import { useEffect, useRef, useState } from 'react'

const FACTOR_LABELS = {
  momentum: 'Momentum',
  quality: 'Quality',
  growth: 'Growth',
  value: 'Value',
  low_vol: 'Low Volatility',
}

const FALLBACK_STRATEGIES = {
  balanced: {
    label: 'Balanced (Classic)',
    mode: 'weights',
    weights: { momentum: 0.30, quality: 0.20, growth: 0.15, value: 0.15, low_vol: 0.20 },
    desc: 'An even mix of price trend and fundamentals — the original all-weather default.',
  },
}

const FIXED_NOTE = {
  formula: "This strategy uses a fixed formula — factor weights aren't customizable.",
  combined: "This strategy runs every other strategy and keeps their common picks — factor weights aren't customizable here.",
}

export default function Controls({ params, cfg, onChange, onRun, running }) {
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)

  const update = (key, value) => onChange({ ...params, [key]: value })
  const updateWeight = (factor, value) =>
    onChange({ ...params, weights: { ...params.weights, [factor]: Number(value) } })

  const strategies = cfg?.strategies || FALLBACK_STRATEGIES
  const activeKey = params.strategy_key
  const active = strategies[activeKey]
  const weightSum = Object.values(params.weights).reduce((a, b) => a + b, 0)

  const selectStrategy = (key, s) => {
    onChange({
      ...params,
      strategy_key: key,
      factor_mode: s.mode === 'weights' ? 'all' : (s.mode === 'combined' ? 'combined' : s.factor_mode),
      weights: s.mode === 'weights' ? { ...s.weights } : params.weights,
    })
    setMenuOpen(false)
  }

  useEffect(() => {
    if (!menuOpen) return
    const onDocClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false)
    }
    const onEsc = (e) => { if (e.key === 'Escape') setMenuOpen(false) }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onEsc)
    }
  }, [menuOpen])

  return (
    <div className="panel controls controls-horizontal">
      <div className="controls-row">
        <label className="control-field control-field-capital">
          Capital (₹)
          <input
            type="number"
            min="1000"
            step="1000"
            value={params.capital}
            onChange={(e) => update('capital', Number(e.target.value))}
          />
        </label>

        <div className="control-field control-field-strategy">
          <span className="control-field-label">Strategy</span>
          <div className="strategy-select" ref={menuRef}>
            <button type="button" className="strategy-select-trigger" onClick={() => setMenuOpen((v) => !v)}>
              <div className="strategy-select-text">
                <div className="strategy-select-label">{active?.label || 'Select strategy'}</div>
              </div>
              <span className={`strategy-select-chevron ${menuOpen ? 'open' : ''}`}>▾</span>
            </button>

            {menuOpen && (
              <div className="strategy-menu" role="listbox">
                {Object.entries(strategies).map(([key, s]) => (
                  <button
                    key={key}
                    type="button"
                    role="option"
                    aria-selected={activeKey === key}
                    className={`strategy-menu-item ${activeKey === key ? 'selected' : ''}`}
                    onClick={() => selectStrategy(key, s)}
                  >
                    <div className="strategy-menu-item-title">{s.label}</div>
                    <div className="strategy-menu-item-desc">{s.desc}</div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {active?.mode === 'weights' && (
          <button type="button" className="link-toggle control-field-toggle" onClick={() => setShowAdvanced((v) => !v)}>
            {showAdvanced ? 'Hide' : 'Customize'} weights
          </button>
        )}

        <div className="control-field-actions">
          <button className="btn-primary" onClick={onRun} disabled={running}>
            {running ? 'Running…' : 'Run Screener'}
          </button>
        </div>
      </div>

      {active?.desc && <p className="panel-hint strategy-active-desc">{active.desc}</p>}

      {active?.mode === 'weights' && showAdvanced && (
        <div className="advanced-weights advanced-weights-horizontal">
          <div className="weight-sum-row">
            <span className={`weight-sum ${Math.abs(weightSum - 1) > 0.02 ? 'warn' : ''}`}>sum {weightSum.toFixed(2)}</span>
          </div>
          <div className="slider-grid">
            {Object.entries(FACTOR_LABELS).map(([key, label]) => (
              <div className="slider-row" key={key}>
                <span className="slider-label">{label}</span>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={params.weights[key]}
                  onChange={(e) => updateWeight(key, e.target.value)}
                />
                <span className="slider-value">{Math.round(params.weights[key] * 100)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {active?.mode !== 'weights' && (
        <p className="panel-hint strategy-fixed-note">{FIXED_NOTE[active?.mode] || FIXED_NOTE.formula}</p>
      )}
    </div>
  )
}
