"""G. Gap and slippage losses are modelled (and gap losses can exceed the risk budget)."""

from __future__ import annotations

import datetime as dt
import sqlite3
from decimal import Decimal

from jtl.domain import Side
from jtl.simulator.costs import CostModel
from jtl.simulator.engine import run_replay
from tests.conftest import make_series


def test_costs_are_always_adverse(cfg):
    cm = CostModel(cfg.simulator)
    ref = Decimal("100")
    assert cm.fill_price(Side.BUY, ref) > ref
    assert cm.fill_price(Side.SELL, ref) < ref
    assert cm.fees(Side.SELL, Decimal("2"), Decimal(100)) > 0
    assert cm.fill_time(dt.datetime(2024, 3, 4, 9, 30, tzinfo=dt.UTC)).second == 2


def _run_gap(tmp_path, small_cfg, gap_open: float):
    closes = [100 + i * 0.5 for i in range(30)]
    opens = list(closes)
    closes += [gap_open, gap_open]
    opens += [gap_open, gap_open]
    r = run_replay(small_cfg, make_series(closes, opens=opens), tmp_path / f"g{gap_open}.db")
    c = sqlite3.connect(tmp_path / f"g{gap_open}.db")
    fills = c.execute("SELECT side, qty, price, reference_price, kind FROM fills ORDER BY rowid").fetchall()
    c.close()
    return r, fills


def test_gap_through_stop_fills_at_open_and_loses_more_than_budget(tmp_path, small_cfg):
    # max_abs_daily_return is 15%; a 12% overnight gap is plausible data -> stop gapped through
    _r, fills = _run_gap(tmp_path, small_cfg, round((100 + 29 * 0.5) * 0.88, 2))
    kinds = [f[4] for f in fills]
    assert "stop_gap" in kinds
    buy = next(f for f in fills if f[0] == "buy")
    stop = next(f for f in fills if f[4] == "stop_gap")
    loss = (Decimal(buy[2]) - Decimal(stop[2])) * Decimal(buy[1])
    assert Decimal(stop[2]) < Decimal(stop[3])  # slippage below the gapped open
    assert loss > Decimal("5.00")  # exceeds the 0.5% * $1000 modelled risk budget


def test_slippage_makes_round_trip_lose_on_flat_prices(tmp_path, small_cfg):
    closes = [100 + i * 0.5 for i in range(25)] + [112.0] * 30  # up then flat -> eventual exit
    run_replay(small_cfg, make_series(closes), tmp_path / "f.db")
    c = sqlite3.connect(tmp_path / "f.db")
    rows = c.execute("SELECT side, price, reference_price, fees FROM fills").fetchall()
    c.close()
    for side, price, ref, _fees in rows:
        assert (Decimal(price) > Decimal(ref)) if side == "buy" else (Decimal(price) < Decimal(ref))
