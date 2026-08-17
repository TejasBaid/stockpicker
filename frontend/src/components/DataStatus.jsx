export default function DataStatus({ status, onRefresh, refreshing }) {
  if (!status) return null

  let freshness = 'No data cached yet'
  if (status.prices_age_hours != null) {
    freshness = `Data cached ${status.prices_age_hours < 1
      ? `${Math.round(status.prices_age_hours * 60)} min ago`
      : `${status.prices_age_hours.toFixed(1)} hr ago`} · ${status.n_tickers ?? '?'} stocks`
  }

  return (
    <div className="data-status">
      <span className={`status-dot ${status.ready ? 'ok' : 'bad'}`} />
      <span>{status.refreshing ? (status.refresh_message || 'Refreshing…') : freshness}</span>
      {status.refresh_error && <span className="status-error">Last refresh failed: {status.refresh_error}</span>}
      <button className="btn-secondary btn-small" onClick={onRefresh} disabled={refreshing || status.refreshing}>
        {refreshing || status.refreshing ? 'Refreshing…' : 'Refresh Market Data'}
      </button>
    </div>
  )
}
