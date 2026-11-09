"""Additional simple baseline bots (signals only; same risk engine and costs as every other bot)."""

from __future__ import annotations

import datetime as dt

from jtl.market_data.models import BarSeries
from jtl.strategy.base import Signal, Target, check_view


class Momentum:
    """Time-series momentum: LONG when the close is above the close `lookback` sessions ago."""

    def __init__(self, symbol: str, lookback: int = 126):
        if not 5 <= lookback <= 400:
            raise ValueError("lookback must be 5..400")
        self.symbol, self.lookback = symbol, lookback
        self.name = f"mom{lookback}"
        self.title = f"Momentum ({lookback}-day return > 0)"

    @property
    def warmup(self) -> int:
        return self.lookback + 1

    def signal(self, view: BarSeries, as_of: dt.date) -> Signal | None:
        if not check_view(self, view, as_of):
            return None
        now, then = view.bars[-1].close, view.bars[-1 - self.lookback].close
        ret = now / then - 1
        return Signal(
            strategy=self.name,
            symbol=self.symbol,
            session=as_of,
            target=Target.LONG if ret > 0 else Target.FLAT,
            metrics={"lookback_return": round(ret, 6)},
        )


class AlwaysLong:
    """Buy-and-hold *under the same risk rules* (small position, 5% protective stop, breakers)."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.name = "hold"
        self.title = "Buy & hold (risk-limited)"

    @property
    def warmup(self) -> int:
        return 1

    def signal(self, view: BarSeries, as_of: dt.date) -> Signal | None:
        if not check_view(self, view, as_of):
            return None
        return Signal(strategy=self.name, symbol=self.symbol, session=as_of, target=Target.LONG)


def default_lineup(symbol: str) -> list:
    """The bots compared by `jtl compare`. All get identical cash, costs and risk limits."""
    from jtl.strategy.sma_trend import SmaTrend

    return [
        SmaTrend(symbol, 50, 200),
        SmaTrend(symbol, 20, 100),
        SmaTrend(symbol, 10, 50),
        Momentum(symbol, 126),
        Momentum(symbol, 63),
        AlwaysLong(symbol),
    ]
