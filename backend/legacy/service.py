from __future__ import annotations

import pandas as pd

from . import config, data, factors, portfolio, regime as regime_mod


def get_regime() -> dict:
    prices, _, _ = data.load_cached()
    index_prices = prices[config.INDEX_TICKER].dropna()
    return regime_mod.detect_regime(index_prices)


def _load_fundamentals_with_meta() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    prices, volumes, fundamentals = data.load_cached()
    meta = data.load_universe_meta()

    if "name" not in fundamentals.columns or fundamentals["name"].isna().all():
        fundamentals = fundamentals.copy()
        fundamentals["name"] = meta["csv_name"].reindex(fundamentals.index)
    if "sector" not in fundamentals.columns:
        fundamentals["sector"] = "Unknown"
    fundamentals["sector"] = fundamentals["sector"].fillna(meta["csv_industry"]).fillna("Unknown")
    return prices, volumes, fundamentals, meta


def list_sectors() -> list[dict]:
    _, _, fundamentals, _ = _load_fundamentals_with_meta()
    counts = fundamentals["sector"].fillna("Unknown").value_counts()
    return [{"sector": s, "count": int(c)} for s, c in counts.items()]


def search_stocks(query: str, limit: int = 15) -> list[dict]:
    _, _, fundamentals, _ = _load_fundamentals_with_meta()
    q = query.strip().upper()
    if not q:
        return []
    df = fundamentals.reset_index().rename(columns={"index": "ticker"})
    df["ticker_short"] = df["ticker"].str.replace(".NS", "", regex=False)
    mask = df["ticker_short"].str.upper().str.contains(q, na=False) | df["name"].astype(str).str.upper().str.contains(q, na=False)
    hits = df[mask].head(limit)
    return [
        {"ticker": row["ticker_short"], "name": row["name"], "sector": row.get("sector", "Unknown")}
        for _, row in hits.iterrows()
    ]


def get_stock_detail(ticker: str, weights: dict | None = None, factor_mode: str = "all") -> dict:
    prices, volumes, fundamentals, _ = _load_fundamentals_with_meta()
    full_ticker = ticker.upper() if ticker.upper().endswith(".NS") else f"{ticker.upper()}.NS"
    if full_ticker not in prices.columns:
        raise KeyError(f"Unknown ticker: {ticker}")

    w = {**config.DEFAULT_WEIGHTS, **(weights or {})}
    # "combined" is a set-membership screen across the whole universe, not a
    # per-stock formula — build_scores doesn't know that key, so it falls
    # through to the classic weighted blend here, same as "all".
    scores = factors.build_scores(prices, fundamentals, w, factor_mode=factor_mode)
    if full_ticker not in scores.index:
        raise KeyError(f"Not enough data to score {ticker}")

    stock_prices = prices.drop(columns=[config.INDEX_TICKER], errors="ignore")
    liq = factors.liquidity_value_cr(stock_prices, volumes)
    uptrend = factors.trend_qualifier(stock_prices)
    stop = factors.atr_stop_levels(prices[[full_ticker]])

    row = scores.loc[full_ticker].to_dict()
    fund_row = fundamentals.loc[full_ticker].to_dict() if full_ticker in fundamentals.index else {}
    rank = int((scores["composite"].rank(ascending=False) - 1).loc[full_ticker]) + 1

    close_price = float(prices[full_ticker].iloc[-1])
    trailing_year = prices[full_ticker].dropna().iloc[-config.LOOKBACK_DAYS:]
    week52_high = float(trailing_year.max()) if not trailing_year.empty else None
    week52_low = float(trailing_year.min()) if not trailing_year.empty else None

    sectors = fundamentals["sector"].fillna("Unknown") if "sector" in fundamentals.columns else pd.Series("Unknown", index=prices.columns)
    strategy_scores = []
    for key, s in config.STRATEGIES.items():
        if s["mode"] == "combined":
            continue
        composite = _strategy_composite(s, scores, prices, fundamentals, sectors)
        s_rank = int((composite.rank(ascending=False) - 1).loc[full_ticker]) + 1
        strategy_scores.append({
            "key": key,
            "label": s["label"],
            "composite": _safe_float(composite.get(full_ticker)),
            "rank": s_rank,
            "universe_size": int(composite.shape[0]),
        })

    return {
        "ticker": ticker.upper().replace(".NS", ""),
        "name": fund_row.get("name", ticker),
        "sector": fund_row.get("sector", "Unknown"),
        "factor_mode": factor_mode,
        "close_price": close_price,
        "week52_high": week52_high,
        "week52_low": week52_low,
        "liquidity_cr": float(liq.get(full_ticker)) if pd.notna(liq.get(full_ticker)) else None,
        "above_200sma": bool(uptrend.get(full_ticker)) if pd.notna(uptrend.get(full_ticker)) else None,
        "stop_loss": float(stop.get(full_ticker)) if pd.notna(stop.get(full_ticker)) else None,
        "rank_of_universe": rank,
        "universe_size": int(scores.shape[0]),
        "strategy_scores": strategy_scores,
        "scores": {
            "momentum": _safe_float(row.get("momentum")),
            "quality": _safe_float(row.get("quality")),
            "growth": _safe_float(row.get("growth")),
            "value": _safe_float(row.get("value")),
            "low_vol": _safe_float(row.get("low_vol")),
            "composite": _safe_float(row.get("composite")),
        },
        "fundamentals": {
            "pe": _safe_float(fund_row.get("pe")),
            "pb": _safe_float(fund_row.get("pb")),
            "roe": _safe_float(fund_row.get("roe")),
            "debt_equity": _safe_float(fund_row.get("debt_equity")),
            "revenue_growth": _safe_float(fund_row.get("revenue_growth")),
            "earnings_growth": _safe_float(fund_row.get("earnings_growth")),
            "profit_margin": _safe_float(fund_row.get("profit_margin")),
            "market_cap": _safe_float(fund_row.get("market_cap")),
        },
    }


def _safe_float(v):
    try:
        f = float(v)
        return f if f == f else None  # filter NaN
    except (TypeError, ValueError):
        return None


def _strategy_composite(
    s: dict,
    base: pd.DataFrame,
    prices: pd.DataFrame,
    fundamentals: pd.DataFrame,
    sectors: pd.Series,
) -> pd.Series:
    """Composite score for one non-combined strategy entry, off an already-computed
    `base` frame (the classic momentum/quality/growth/value/low_vol columns, which
    build_scores always populates regardless of factor_mode).
    """
    if s["mode"] == "weights":
        w = {**config.DEFAULT_WEIGHTS, **s["weights"]}
        total_w = sum(w.values()) or 1.0
        return sum(
            (w.get(f, 0) / total_w) * base[f].fillna(0) for f in ["momentum", "quality", "growth", "value", "low_vol"]
        )
    return factors.STRATEGY_FORMULAS[s["factor_mode"]](prices, fundamentals, sectors).reindex(base.index).fillna(-3.0)


def _combined_consensus_scores(
    prices: pd.DataFrame,
    fundamentals: pd.DataFrame,
    volumes: pd.DataFrame,
    top_n: int,
    min_liquidity_cr: float,
    require_uptrend: bool,
) -> tuple[pd.DataFrame, int, int]:
    """Run every non-combined strategy and keep stocks that land in the top
    candidate pool of ALL of them — a consensus screen, not a new blend.

    Each strategy's own gated, ranked list contributes its top `candidate_pool`
    names; the returned frame is restricted to the intersection of those sets,
    with "composite" set to the average of each strategy's composite score
    (only used for final ranking/diversified selection within the consensus
    set — membership itself is a hard AND across strategies, not an average).
    """
    sectors = fundamentals["sector"].fillna("Unknown") if "sector" in fundamentals.columns else pd.Series("Unknown", index=prices.columns)
    base = factors.build_scores(prices, fundamentals, config.DEFAULT_WEIGHTS, factor_mode="all")

    sub_strategies = {k: s for k, s in config.STRATEGIES.items() if s.get("mode") in ("weights", "formula")}
    candidate_pool = max(top_n * 4, 25)

    per_strategy_composite = {}
    topk_sets = []
    for key, s in sub_strategies.items():
        composite = _strategy_composite(s, base, prices, fundamentals, sectors)
        scored = base.assign(composite=composite)
        gated = portfolio.apply_gates(scored, prices, volumes, min_liquidity_cr, require_uptrend)
        ranked = gated.dropna(subset=["composite"]).sort_values("composite", ascending=False)
        per_strategy_composite[key] = ranked["composite"]
        topk_sets.append(set(ranked.index[:candidate_pool]))

    consensus = set.intersection(*topk_sets) if topk_sets else set()
    combined = base.loc[base.index.intersection(consensus)].copy()
    if not combined.empty:
        avg_composite = pd.concat(
            [s.reindex(combined.index) for s in per_strategy_composite.values()], axis=1
        ).mean(axis=1)
        combined["composite"] = avg_composite
    return combined, len(sub_strategies), candidate_pool


def run_screen(
    capital: float = config.DEFAULT_CAPITAL,
    top_n: int = config.DEFAULT_TOP_N,
    weights: dict | None = None,
    factor_mode: str = "all",
    max_per_sector: int = config.DEFAULT_MAX_PER_SECTOR,
    min_liquidity_cr: float = config.DEFAULT_MIN_LIQUIDITY_CR,
    require_uptrend: bool = True,
    sectors: list[str] | None = None,
) -> dict:
    prices, volumes, fundamentals, meta = _load_fundamentals_with_meta()

    w = {**config.DEFAULT_WEIGHTS, **(weights or {})}

    index_prices = prices[config.INDEX_TICKER].dropna()
    regime = regime_mod.detect_regime(index_prices)

    consensus_meta = None
    if factor_mode == "combined":
        scores, n_strategies, pool = _combined_consensus_scores(
            prices, fundamentals, volumes, top_n, min_liquidity_cr, require_uptrend
        )
        consensus_meta = {"strategies_combined": n_strategies, "candidate_pool_per_strategy": pool, "consensus_size": int(scores.shape[0])}
    else:
        scores = factors.build_scores(prices, fundamentals, w, factor_mode=factor_mode)

    if sectors:
        allowed = set(sectors)
        keep = fundamentals["sector"].reindex(scores.index).isin(allowed)
        scores = scores[keep]

    if factor_mode == "combined" and scores.empty:
        raise ValueError(
            "No stocks were ranked near the top by every strategy under the current filters. "
            "Try widening the sector selection, lowering the liquidity bar, or use a single strategy instead."
        )

    port = portfolio.construct_portfolio(
        scores, prices, volumes, fundamentals,
        capital=capital, top_n=top_n, regime=regime,
        max_per_sector=max_per_sector,
        min_liquidity_cr=min_liquidity_cr,
        max_pair_corr=config.DEFAULT_MAX_PAIR_CORR,
        require_uptrend=require_uptrend,
    )

    total_deployed = float(port["actual_cost"].sum())
    effective_capital = capital * regime["deploy_pct"]

    port = port.rename_axis("ticker")
    port_out = port.reset_index()
    port_out = port_out.replace([float("inf"), float("-inf")], None)
    port_out = port_out.astype(object).where(pd.notnull(port_out), None)

    return {
        "regime": regime,
        "weights_used": w,
        "factor_mode": factor_mode,
        "consensus": consensus_meta,
        "capital": capital,
        "effective_capital": effective_capital,
        "total_deployed": total_deployed,
        "cash_remaining": capital - total_deployed,
        "regime_cash_buffer": capital - effective_capital,
        "universe_size": int(scores.shape[0]),
        "gated_size": int(portfolio.apply_gates(scores, prices, volumes, min_liquidity_cr, require_uptrend).shape[0]),
        "portfolio": port_out.to_dict(orient="records"),
    }
