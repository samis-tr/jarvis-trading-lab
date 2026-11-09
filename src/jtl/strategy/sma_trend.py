"""Daily trend baseline: LONG when SMA(fast) > SMA(slow) on the confirmed close, else FLAT.

The signal for session t uses only bars with session <= t and is executed at the OPEN of the next
session (t+1). The strategy receives a point-in-time view and asserts it never sees the future.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from jtl.market_data.models import BarSeries


class Target(StrEnum):
    LONG = "long"
    FLAT = "flat"


class Signal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    symbol: str
    session: dt.date  # decided on this session's confirmed close
    target: Target
    fast_sma: float
    slow_sma: float


class SmaTrend:
    def __init__(self, symbol: str, fast: int = 50, slow: int = 200):
        if not 2 <= fast < slow:
            raise ValueError("need 2 <= fast < slow")
        self.symbol, self.fast, self.slow = symbol, fast, slow

    @property
    def warmup(self) -> int:
        return self.slow

    def signal(self, view: BarSeries, as_of: dt.date) -> Signal | None:
        if view.symbol != self.symbol:
            raise ValueError("wrong symbol")
        if view.bars and view.bars[-1].session > as_of:
            raise AssertionError("look-ahead: view contains bars after as_of")
        if not view.bars or view.bars[-1].session != as_of or len(view.bars) < self.slow:
            return None
        closes = [b.close for b in view.bars[-self.slow :]]
        slow = sum(closes) / self.slow
        fast = sum(closes[-self.fast :]) / self.fast
        return Signal(
            symbol=self.symbol,
            session=as_of,
            target=Target.LONG if fast > slow else Target.FLAT,
            fast_sma=round(fast, 6),
            slow_sma=round(slow, 6),
        )
