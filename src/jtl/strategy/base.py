"""Strategy interface. A strategy only turns a point-in-time view into a LONG/FLAT *signal*.

It cannot size positions, submit orders, see the account, or change risk limits.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from jtl.market_data.models import BarSeries


class Target(StrEnum):
    LONG = "long"
    FLAT = "flat"


class Signal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    strategy: str
    symbol: str
    session: dt.date  # decided on this session's confirmed close; executed at the next open
    target: Target
    metrics: dict[str, float] = {}


@runtime_checkable
class Strategy(Protocol):
    name: str  # short id, [a-z0-9-], used in order IDs
    title: str  # human-readable
    symbol: str

    @property
    def warmup(self) -> int: ...

    def signal(self, view: BarSeries, as_of: dt.date) -> Signal | None: ...


def check_view(strategy: Strategy, view: BarSeries, as_of: dt.date) -> bool:
    """Common look-ahead / warm-up guard. Returns False when there is not enough history yet."""
    if view.symbol != strategy.symbol:
        raise ValueError("wrong symbol")
    if view.bars and view.bars[-1].session > as_of:
        raise AssertionError("look-ahead: view contains bars after as_of")
    return bool(view.bars) and view.bars[-1].session == as_of and len(view.bars) >= strategy.warmup
