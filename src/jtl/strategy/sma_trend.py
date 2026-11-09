"""Daily trend baseline: LONG when SMA(fast) > SMA(slow) on the confirmed close, else FLAT.

The signal for session t uses only bars with session <= t and is executed at the OPEN of the next
session (t+1). The strategy receives a point-in-time view and asserts it never sees the future.
"""

from __future__ import annotations

import datetime as dt

from jtl.market_data.models import BarSeries
from jtl.strategy.base import Signal, Target, check_view


class SmaTrend:
    def __init__(self, symbol: str, fast: int = 50, slow: int = 200):
        if not 2 <= fast < slow:
            raise ValueError("need 2 <= fast < slow")
        self.symbol, self.fast, self.slow = symbol, fast, slow
        self.name = f"sma{fast}-{slow}"
        self.title = f"Moving-average trend {fast}/{slow}"

    @property
    def warmup(self) -> int:
        return self.slow

    def signal(self, view: BarSeries, as_of: dt.date) -> Signal | None:
        if not check_view(self, view, as_of):
            return None
        closes = [b.close for b in view.bars[-self.slow :]]
        slow = sum(closes) / self.slow
        fast = sum(closes[-self.fast :]) / self.fast
        return Signal(
            strategy=self.name,
            symbol=self.symbol,
            session=as_of,
            target=Target.LONG if fast > slow else Target.FLAT,
            metrics={"fast_sma": round(fast, 6), "slow_sma": round(slow, 6)},
        )
