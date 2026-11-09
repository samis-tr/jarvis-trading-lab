"""Performance analytics and benchmarks. Every output is marked HYPOTHETICAL."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from jtl import HYPOTHETICAL_BANNER
from jtl.market_data.models import BarSeries
from jtl.storage.db import Storage


@dataclass(frozen=True)
class Metrics:
    label: str
    start: dt.date
    end: dt.date
    start_value: float
    end_value: float
    total_return: float
    cagr: float
    max_drawdown: float
    sharpe: float | None
    trades: int = 0
    fees_paid: float = 0.0
    hypothetical: bool = True
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["start"], d["end"] = self.start.isoformat(), self.end.isoformat()
        d["disclaimer"] = HYPOTHETICAL_BANNER
        return d


def metrics_from_curve(
    label: str,
    curve: list[tuple[dt.date, float]],
    *,
    trades: int = 0,
    fees: float = 0.0,
    notes: list[str] | None = None,
) -> Metrics:
    if len(curve) < 2:
        raise ValueError("need at least two points")
    v0, v1 = curve[0][1], curve[-1][1]
    years = max((curve[-1][0] - curve[0][0]).days / 365.25, 1e-9)
    peak, mdd = -math.inf, 0.0
    rets = []
    for i, (_, v) in enumerate(curve):
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
        if i:
            rets.append(v / curve[i - 1][1] - 1)
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1)
    sharpe = (mean / math.sqrt(var) * math.sqrt(252)) if var > 0 else None
    return Metrics(
        label=label,
        start=curve[0][0],
        end=curve[-1][0],
        start_value=v0,
        end_value=v1,
        total_return=v1 / v0 - 1,
        cagr=(v1 / v0) ** (1 / years) - 1,
        max_drawdown=mdd,
        sharpe=sharpe,
        trades=trades,
        fees_paid=fees,
        notes=notes or [],
    )


def strategy_metrics(storage: Storage, label: str = "SMA trend (simulated)") -> Metrics:
    curve = [
        (dt.date.fromisoformat(s), float(e))
        for s, e in storage.query("SELECT session, equity FROM equity ORDER BY session")
    ]
    trades = storage.query("SELECT COUNT(*), COALESCE(SUM(CAST(fees AS REAL)),0) FROM fills")[0]
    return metrics_from_curve(
        label,
        curve,
        trades=trades[0],
        fees=float(trades[1]),
        notes=["price-only: dividends are NOT credited to the simulated ledger"],
    )


def buy_and_hold(series: BarSeries, start: dt.date, end: dt.date, capital: float, label: str) -> Metrics:
    bars = [b for b in series.bars if start <= b.session <= end]
    if len(bars) < 2:
        raise ValueError("not enough bars for benchmark")
    q = capital / bars[0].open  # bought at the first session's open; point 0 = capital before the buy
    curve = [(bars[0].session - dt.timedelta(days=1), capital)] + [(b.session, q * b.close) for b in bars]
    return metrics_from_curve(label, curve, notes=[f"no costs; {series.provenance.adjustment.value}-adjusted"])


def cash_benchmark(start: dt.date, end: dt.date, capital: float) -> Metrics:
    return Metrics(
        label="Cash (0% interest assumed)",
        start=start,
        end=end,
        start_value=capital,
        end_value=capital,
        total_return=0.0,
        cagr=0.0,
        max_drawdown=0.0,
        sharpe=None,
        notes=["no interest modelled"],
    )


def fmt_money(x: float | Decimal) -> str:
    return f"${float(x):,.2f}"
