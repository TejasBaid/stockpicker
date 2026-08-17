const LABELS = {
  GREEN: { title: 'BULL — Full Deployment', icon: '●' },
  YELLOW: { title: 'CAUTION — Partial Deployment', icon: '▲' },
  RED: { title: 'DEFENSIVE — Capital Protection', icon: '■' },
}

export default function RegimeBanner({ regime }) {
  if (!regime) return null
  const meta = LABELS[regime.state] || LABELS.YELLOW
  return (
    <div className={`regime-banner regime-${regime.state.toLowerCase()}`}>
      <div className="regime-headline">
        <span className="regime-icon">{meta.icon}</span>
        <span>{meta.title}</span>
        <span className="regime-deploy">{Math.round(regime.deploy_pct * 100)}% deployed</span>
      </div>
      <div className="regime-metrics">
        <Metric label="Nifty 50" value={regime.current.toLocaleString('en-IN', { maximumFractionDigits: 0 })} />
        <Metric label="50-SMA" value={regime.sma_fast.toLocaleString('en-IN', { maximumFractionDigits: 0 })} />
        <Metric label="200-SMA" value={regime.sma_slow.toLocaleString('en-IN', { maximumFractionDigits: 0 })} />
        <Metric label="1M Return" value={pct(regime.ret_1m)} signed />
        <Metric label="3M Return" value={pct(regime.ret_3m)} signed />
        <Metric label="Ann. Vol" value={pct(regime.idx_vol)} />
        <Metric label="Golden Cross" value={regime.golden_cross ? 'Yes' : 'No'} />
      </div>
    </div>
  )
}

function pct(v) {
  return `${(v * 100).toFixed(2)}%`
}

function Metric({ label, value }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
    </div>
  )
}
