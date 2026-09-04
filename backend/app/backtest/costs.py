"""Indian equity transaction costs.

Modelled explicitly rather than as a flat percentage, because the components
behave differently: STT and stamp duty are one-sided, GST applies only to
brokerage and exchange charges, and the whole thing is dwarfed by slippage for
anything but the largest names. Costs are what turn a good backtest into an
honest one -- a high-turnover strategy can look excellent gross and lose money
net.

Rates are delivery-basis (CNC) equity, current as of 2026. They are settings,
not constants, because they change.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    brokerage_pct: float = 0.0  # most discount brokers: zero on delivery
    stt_buy_pct: float = 0.001  # 0.1% on buy
    stt_sell_pct: float = 0.001  # 0.1% on sell
    exchange_pct: float = 0.0000297  # NSE transaction charge
    sebi_pct: float = 0.000001  # SEBI turnover fee
    stamp_buy_pct: float = 0.00015  # 0.015%, buy side only
    gst_pct: float = 0.18  # on brokerage + exchange charges
    slippage_pct: float = 0.0010  # 10 bps: the dominant real-world cost

    def cost(self, value: float, side: str) -> float:
        """Total cost in rupees for a trade of ``value`` rupees."""
        if value <= 0:
            return 0.0
        brokerage = value * self.brokerage_pct
        exchange = value * self.exchange_pct
        gst = (brokerage + exchange) * self.gst_pct
        sebi = value * self.sebi_pct
        slippage = value * self.slippage_pct

        if side.upper() == "BUY":
            stt = value * self.stt_buy_pct
            stamp = value * self.stamp_buy_pct
        else:
            stt = value * self.stt_sell_pct
            stamp = 0.0

        return brokerage + exchange + gst + sebi + stt + stamp + slippage

    def round_trip_pct(self) -> float:
        """Approximate cost of buying and selling ₹100, as a percentage."""
        return (self.cost(100.0, "BUY") + self.cost(100.0, "SELL")) / 100.0 * 100.0


DEFAULT_COSTS = CostModel()
ZERO_COSTS = CostModel(
    brokerage_pct=0.0,
    stt_buy_pct=0.0,
    stt_sell_pct=0.0,
    exchange_pct=0.0,
    sebi_pct=0.0,
    stamp_buy_pct=0.0,
    gst_pct=0.0,
    slippage_pct=0.0,
)
