"""Research discipline: data sufficiency, in-sample / sealed out-of-sample split.

* Parameter selection may only see `InSample` data (enforced by type + runtime check).
* The held-out slice is wrapped in `SealedHoldout`; opening it is journaled and allowed once.
* The LLM / Jarvis may *explain* research but cannot change active strategy or risk config
  (config objects are frozen; there is no write API).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from jtl.errors import InsufficientData, SafetyError
from jtl.market_data.models import BarSeries
from jtl.market_data.validation import check_sufficient


@dataclass(frozen=True)
class InSample:
    series: BarSeries


class SealedHoldout:
    def __init__(self, series: BarSeries):
        self._series = series
        self.first_session: dt.date = series.bars[0].session
        self.opened_reason: str | None = None

    def open_for_final_evaluation(self, reason: str, on_open: Callable[[str], None] | None = None) -> BarSeries:
        if self.opened_reason is not None:
            raise SafetyError("holdout already opened once - re-use would leak test performance into selection")
        if len(reason.strip()) < 10:
            raise SafetyError("give a reason for opening the holdout")
        self.opened_reason = reason
        if on_open:
            on_open(reason)
        return self._series


def split(series: BarSeries, *, holdout_fraction: float, min_years: float) -> tuple[InSample, SealedHoldout]:
    check_sufficient(series, min_years)
    n = len(series.bars)
    cut = int(n * (1 - holdout_fraction))
    if cut < 260 or n - cut < 120:
        raise InsufficientData("not enough data for a meaningful in-sample / holdout split")
    ins = BarSeries(symbol=series.symbol, provenance=series.provenance, bars=series.bars[:cut])
    hold = BarSeries(symbol=series.symbol, provenance=series.provenance, bars=series.bars[cut:])
    return InSample(ins), SealedHoldout(hold)


def select_parameters(
    data: InSample, grid: Iterable[tuple[int, int]], score: Callable[[BarSeries, int, int], float]
) -> tuple[int, int]:
    """Pick (fast, slow) by in-sample score only."""
    if not isinstance(data, InSample):
        raise SafetyError("parameter selection must use InSample data only")
    best, best_score = None, float("-inf")
    for fast, slow in grid:
        sc = score(data.series, fast, slow)
        if sc > best_score:
            best, best_score = (fast, slow), sc
    if best is None:
        raise ValueError("empty grid")
    return best
