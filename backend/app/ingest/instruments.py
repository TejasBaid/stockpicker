"""Instrument master and the Nifty 200 universe.

Identity comes from the NSE trading symbol, which both providers share: Groww's
master carries it as ``trading_symbol`` and every Indian Stock API endpoint
keys off it directly.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models.market import Instrument, Universe, UniverseMember
from app.providers.groww import GrowwClient

log = structlog.get_logger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
NIFTY200_CSV = DATA_DIR / "nifty200.csv"

NIFTY200_SLUG = "nifty200"
BENCHMARK_SYMBOL = "NIFTY"


def sync_instrument_master(db: Session, client: GrowwClient | None = None) -> int:
    """Refresh instrument identity from Groww's master list."""
    client = client or GrowwClient()
    df = client.equity_instruments()

    rows = []
    for r in df.itertuples(index=False):
        symbol = str(r.trading_symbol).strip().upper()
        if not symbol:
            continue
        rows.append(
            {
                "symbol": symbol,
                "isin": (str(r.isin).strip() or None) if r.isin else None,
                "name": str(r.name).strip() or symbol,
                "groww_symbol": str(r.groww_symbol).strip() or None,
                "groww_token": str(r.exchange_token).strip() or None,
                "lot_size": int(r.lot_size) if r.lot_size and str(r.lot_size).isdigit() else None,
                "exchange": "NSE",
            }
        )

    written = 0
    for chunk_start in range(0, len(rows), 500):
        chunk = rows[chunk_start : chunk_start + 500]
        stmt = pg_insert(Instrument).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol"],
            set_={
                "isin": stmt.excluded.isin,
                "name": stmt.excluded.name,
                "groww_symbol": stmt.excluded.groww_symbol,
                "groww_token": stmt.excluded.groww_token,
                "lot_size": stmt.excluded.lot_size,
            },
        )
        db.execute(stmt)
        written += len(chunk)
    db.commit()
    log.info("ingest.instruments.synced", count=written)
    return written


def seed_nifty200(db: Session) -> tuple[int, list[str]]:
    """Create the Nifty 200 universe from the bundled constituent list.

    Returns the member count and any symbols missing from the instrument master
    (usually renames, which need investigating rather than silently dropping).
    """
    if not NIFTY200_CSV.exists():
        raise FileNotFoundError(f"Missing constituent list at {NIFTY200_CSV}")

    with NIFTY200_CSV.open(newline="", encoding="utf-8-sig") as fh:
        rows = [
            {
                "symbol": row["Symbol"].strip().upper(),
                "name": row["Company Name"].strip(),
                "sector": row["Industry"].strip(),
                "isin": row["ISIN Code"].strip(),
            }
            for row in csv.DictReader(fh)
            if row.get("Symbol")
        ]

    # NSE publishes placeholder rows for corporate actions that have not listed
    # yet -- the pending Vedanta demerger appears as "Dummy Vedanta Ltd. 1-4"
    # with synthetic ISINs (DU1205A01025). They are not tradeable and have no
    # data at either provider, so they are dropped rather than left to fail on
    # every ingest run. Real Indian equity ISINs all begin "IN".
    constituents = [c for c in rows if c["isin"].upper().startswith("IN")]
    if len(constituents) != len(rows):
        dropped = sorted({c["symbol"] for c in rows} - {c["symbol"] for c in constituents})
        log.info("ingest.universe.placeholders_skipped", symbols=dropped)

    # The constituent list is the better sector source: Groww's master has none.
    for c in constituents:
        stmt = pg_insert(Instrument).values(
            symbol=c["symbol"], name=c["name"], sector=c["sector"], isin=c["isin"], exchange="NSE"
        )
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["symbol"],
                set_={"sector": stmt.excluded.sector, "isin": stmt.excluded.isin},
            )
        )

    # The benchmark is an index, not an equity, but it needs bars like any other.
    stmt = pg_insert(Instrument).values(
        symbol=BENCHMARK_SYMBOL, name="Nifty 50", exchange="NSE", fundamentals_available=False
    )
    db.execute(stmt.on_conflict_do_nothing(index_elements=["symbol"]))

    universe = db.scalar(select(Universe).where(Universe.slug == NIFTY200_SLUG))
    if universe is None:
        universe = Universe(
            slug=NIFTY200_SLUG,
            name="Nifty 200",
            description="NSE Nifty 200 constituents -- the screening universe.",
            is_system=True,
        )
        db.add(universe)
        db.flush()

    for c in constituents:
        stmt = pg_insert(UniverseMember).values(universe_id=universe.id, symbol=c["symbol"])
        db.execute(stmt.on_conflict_do_nothing(index_elements=["universe_id", "symbol"]))

    db.commit()

    known = set(db.scalars(select(Instrument.symbol)).all())
    missing = sorted({c["symbol"] for c in constituents} - known)
    log.info("ingest.universe.seeded", count=len(constituents), missing=len(missing))
    return len(constituents), missing


def resolve_vendor_aliases(db: Session, client: Any, symbols: list[str]) -> dict[str, str]:
    """Find the name the fundamentals vendor knows a symbol by.

    The vendor's /stock endpoint keys off the NSE symbol, but it cannot resolve
    symbols containing "&" -- M&M and GVT&D 404 even when URL-encoded. Its
    /industry_search endpoint does return those companies and reports their NSE
    code, so the alias is discovered rather than hardcoded: search by company
    name, then keep the result whose NSE code matches the symbol we wanted.
    """
    resolved: dict[str, str] = {}
    for symbol in symbols:
        inst = db.get(Instrument, symbol)
        if inst is None or inst.vendor_lookup_name:
            continue
        # Search widening: a one-word query is ambiguous for names like
        # "GE Vernova T&D India", so fall back to progressively more terms.
        words = (inst.name or symbol).split()
        candidates = [" ".join(words[:n]) for n in (1, 2, 3) if words[:n]]
        matched = False
        for query in dict.fromkeys(candidates):
            try:
                results = client.industry_search(query)
            except Exception as exc:
                log.warning("ingest.alias.search_failed", symbol=symbol, error=str(exc)[:160])
                break
            if not isinstance(results, list):
                continue
            for row in results:
                if not isinstance(row, dict):
                    continue
                if str(row.get("exchangeCodeNsi", "")).strip().upper() == symbol:
                    name = str(row.get("commonName") or "").strip()
                    if name:
                        inst.vendor_lookup_name = name[:200]
                        resolved[symbol] = name
                        log.info("ingest.alias.resolved", symbol=symbol, lookup_name=name)
                        matched = True
                    break
            if matched:
                break
        if not matched:
            log.warning("ingest.alias.unresolved", symbol=symbol, name=inst.name)
    db.commit()
    return resolved


def universe_symbols(db: Session, slug: str = NIFTY200_SLUG) -> list[str]:
    return list(
        db.scalars(
            select(UniverseMember.symbol)
            .join(Universe, Universe.id == UniverseMember.universe_id)
            .where(Universe.slug == slug)
            .order_by(UniverseMember.symbol)
        ).all()
    )
