"""Point-in-time dating.

Every fundamental row records ``known_on`` -- the date the market could first
have known it. Screens and backtests filter on it, and it is the single thing
that keeps backtest results honest.

The vendor's own ``StatementDate`` is unusable: ``/stock`` reports the same
value (e.g. ``2021-03-31``) for *every* annual period regardless of ``EndDate``,
so trusting it would silently backdate a decade of results into 2021 and
manufacture enormous lookahead bias.

So ``known_on`` is resolved in two tiers:

1. ``ActualReportDate`` / ``ReportedDate`` from ``/stock_forecasts``, which is
   the real announcement timestamp, matched to the fiscal period it belongs to.
2. Otherwise the statutory filing deadline under SEBI (LODR) Regulation 33 --
   45 days after a quarter end, 60 days after a financial year end. This is a
   deliberately *late* estimate: assuming data arrived later than it really did
   understates a backtest's edge, whereas assuming it arrived early invents one.

Rows resolved by tier 2 are flagged ``known_on_estimated`` and surfaced in the
UI, so a result is never quietly presented as more rigorous than it is.
"""

from __future__ import annotations

import datetime as dt

# SEBI (LODR) Regulation 33 filing deadlines.
INTERIM_FILING_LAG_DAYS = 45
ANNUAL_FILING_LAG_DAYS = 60

# How far from a fiscal period end a reported date may sit and still be taken
# as that period's announcement. Results land weeks after period end, never
# before it, and never more than a couple of quarters late.
_MATCH_MIN_DAYS = 0
_MATCH_MAX_DAYS = 200


def _is_plausible(fiscal_end: dt.date, reported: dt.date) -> bool:
    """Results are announced after the period ends, and within a couple of
    quarters of it. Anything else is bad vendor data -- notably the broken
    ``StatementDate``, which backdates every period to the same day."""
    return _MATCH_MIN_DAYS <= (reported - fiscal_end).days <= _MATCH_MAX_DAYS


def statutory_known_on(fiscal_end: dt.date, period_type: str) -> dt.date:
    lag = ANNUAL_FILING_LAG_DAYS if period_type.lower() == "annual" else INTERIM_FILING_LAG_DAYS
    return fiscal_end + dt.timedelta(days=lag)


def resolve_known_on(
    fiscal_end: dt.date,
    period_type: str,
    report_dates: dict[dt.date, dt.date] | None = None,
) -> tuple[dt.date, bool]:
    """Return ``(known_on, estimated)`` for a fiscal period.

    ``report_dates`` maps a fiscal period end to its actual announcement date,
    built from ``/stock_forecasts``.
    """
    if report_dates:
        exact = report_dates.get(fiscal_end)
        if exact is not None and _is_plausible(fiscal_end, exact):
            return exact, False

        # Fiscal-period ends can differ by a few days between the statement and
        # estimate feeds, so accept the closest plausible match.
        best: tuple[int, dt.date] | None = None
        for period_end, reported in report_dates.items():
            gap = abs((period_end - fiscal_end).days)
            if gap <= 10 and reported >= fiscal_end:
                delta = (reported - fiscal_end).days
                if _MATCH_MIN_DAYS <= delta <= _MATCH_MAX_DAYS and (best is None or gap < best[0]):
                    best = (gap, reported)
        if best is not None:
            return best[1], False

    return statutory_known_on(fiscal_end, period_type), True


def parse_date(value: object) -> dt.date | None:
    """Parse the several date shapes the vendors emit."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value).strip()
    if not text or text in {"-", "NA", "null"}:
        return None
    text = text.replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(text).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d %b %Y", "%b %Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
