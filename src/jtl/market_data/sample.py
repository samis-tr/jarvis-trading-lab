"""Seeded SYNTHETIC sample data for offline demos and tests. These are NOT real prices.

A regime-switching random walk on the real NYSE calendar, with quarterly synthetic dividends so
price-only and total-return series differ. Every series is labelled Source.SYNTHETIC.
"""

from __future__ import annotations

import datetime as dt
import math
import random

from jtl.market_data import calendar
from jtl.market_data.models import Adjustment, Bar, BarSeries, Provenance, Source


def synthetic_pair(
    symbol: str = "SPY",
    start: dt.date = dt.date(2015, 1, 2),
    end: dt.date = dt.date(2025, 12, 31),
    seed: int = 7,
    start_price: float = 200.0,
    source: Source = Source.SYNTHETIC,
) -> tuple[BarSeries, BarSeries]:
    """Return (price_only, total_return) synthetic series sharing the same sessions."""
    rng = random.Random(seed)
    sessions = calendar.sessions_in_range(start, end)
    price = start_price
    regime_left = 0
    drift, vol = 0.0, 0.01
    rows: list[tuple[dt.date, float, float, float, float, float, float]] = []
    for s in sessions:
        if regime_left <= 0:
            bull = rng.random() < 0.65
            drift = rng.uniform(0.0003, 0.0009) if bull else rng.uniform(-0.0012, -0.0002)
            vol = rng.uniform(0.006, 0.011) if bull else rng.uniform(0.011, 0.02)
            regime_left = rng.randint(60, 300)
        regime_left -= 1
        gap = rng.gauss(0, vol * 0.4)
        o = price * math.exp(gap)
        c = o * math.exp(drift + rng.gauss(0, vol))
        hi = max(o, c) * (1 + abs(rng.gauss(0, vol * 0.5)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, vol * 0.5)))
        div = round(c * 0.0035, 4) if (s.month in (3, 6, 9, 12) and 15 <= s.day <= 21 and s.weekday() == 4) else 0.0
        rows.append((s, o, hi, lo, c, float(rng.randint(40_000_000, 120_000_000)), div))
        price = c

    price_bars = tuple(
        Bar(session=s, open=round(o, 4), high=round(h, 4), low=round(lo, 4), close=round(c, 4), volume=v)
        for s, o, h, lo, c, v, _ in rows
    )
    # Backward dividend adjustment for the total-return series.
    factors = [1.0] * len(rows)
    f = 1.0
    for i in range(len(rows) - 1, -1, -1):
        factors[i] = f
        div = rows[i][6]
        if div and i > 0:
            f *= 1 - div / rows[i - 1][4]
    tr_bars = tuple(
        Bar(
            session=b.session,
            open=round(b.open * k, 4),
            high=round(b.high * k, 4),
            low=round(b.low * k, 4),
            close=round(b.close * k, 4),
            volume=b.volume,
        )
        for b, k in zip(price_bars, factors, strict=True)
    )
    note = f"seed={seed}; regime-switching random walk; NOT REAL PRICES"
    return (
        BarSeries(
            symbol=symbol, bars=price_bars, provenance=Provenance(source=source, adjustment=Adjustment.SPLIT, note=note)
        ),
        BarSeries(
            symbol=symbol, bars=tr_bars, provenance=Provenance(source=source, adjustment=Adjustment.ALL, note=note)
        ),
    )
