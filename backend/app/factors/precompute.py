"""Nightly factor precomputation.

Factors are never computed in the request path: the web service runs on 512 MB
with ~0.1 CPU, so a screen must be an indexed SELECT plus a weighted sum, not a
pandas job. The maths lands in phase 2; this module owns the contract.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.orm import Session

log = structlog.get_logger(__name__)


def precompute_factors(db: Session, symbols: list[str]) -> dict[str, Any]:
    log.info("factors.precompute.pending", symbols=len(symbols))
    return {"rows": 0, "factors": 0, "note": "factor engine lands in phase 2"}
