"""Execution cost model: half-spread + adverse slippage + latency drift, commissions and sell-side fees.

All adjustments are ADVERSE (buys fill higher, sells lower). Overnight gaps are modelled by filling
at the next session's open, and stops that are gapped through fill at the (worse) open.
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_DOWN, ROUND_UP, Decimal

from jtl.config import SimulatorConfig
from jtl.domain import CENT, Side, d

PX = Decimal("0.0001")
BPS = Decimal(10_000)


class CostModel:
    def __init__(self, cfg: SimulatorConfig):
        self.cfg = cfg
        self.adverse = (d(cfg.half_spread_bps) + d(cfg.slippage_bps) + d(cfg.latency_drift_bps)) / BPS

    def fill_price(self, side: Side, reference: Decimal) -> Decimal:
        if side is Side.BUY:
            return (reference * (1 + self.adverse)).quantize(PX, rounding=ROUND_UP)
        return (reference * (1 - self.adverse)).quantize(PX, rounding=ROUND_DOWN)

    def fees(self, side: Side, qty: Decimal, price: Decimal) -> Decimal:
        f = d(self.cfg.commission_per_order)
        if side is Side.SELL:
            f += qty * price * d(self.cfg.sec_fee_rate)
            f += min(qty * d(self.cfg.finra_taf_per_share), d(self.cfg.finra_taf_max))
        return f.quantize(CENT, rounding=ROUND_UP)

    def fill_time(self, open_time: dt.datetime) -> dt.datetime:
        return open_time + dt.timedelta(seconds=self.cfg.latency_seconds)
