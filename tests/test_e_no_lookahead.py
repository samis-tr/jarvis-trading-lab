"""E. No future information is used: signals use bars <= t and execute at the open of t+1."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

import pytest

from jtl.market_data.models import Bar, BarSeries
from jtl.simulator.engine import run_replay
from jtl.strategy.sma_trend import SmaTrend, Target
from tests.conftest import TEST_PROV, make_series


def test_signal_invariant_to_future_bars(synth):
    strat = SmaTrend("SPY", 50, 200)
    for idx in (250, 400, 600):
        t = synth.bars[idx].session
        a = strat.signal(synth.upto(t), t)
        future_changed = BarSeries(
            symbol="SPY",
            provenance=TEST_PROV,
            bars=synth.bars[: idx + 1]
            + tuple(
                Bar(
                    session=b.session,
                    open=b.open * 3,
                    high=b.high * 3,
                    low=b.low * 3,
                    close=b.close * 3,
                    volume=b.volume,
                )
                for b in synth.bars[idx + 1 :]
            ),
        )
        b = strat.signal(future_changed.upto(t), t)
        assert a == b


def test_strategy_refuses_views_containing_future(synth):
    strat = SmaTrend("SPY", 50, 200)
    t = synth.bars[300].session
    with pytest.raises(AssertionError):
        strat.signal(synth.upto(synth.bars[301].session), t)


def test_warmup_returns_no_signal():
    s = make_series([100.0] * 19)
    assert SmaTrend("SPY", 5, 20).signal(s, s.bars[-1].session) is None


def test_orders_fill_at_next_session_open_never_same_bar(tmp_path, small_cfg):
    closes = [100 + i * 0.4 for i in range(60)]
    opens = [c - 0.2 for c in closes]
    s = make_series(closes, opens=opens)
    run_replay(small_cfg, s, tmp_path / "e.db")
    c = sqlite3.connect(tmp_path / "e.db")
    rows = c.execute(
        "SELECT o.created_session, f.session, f.reference_price FROM orders o JOIN fills f "
        "USING(client_order_id) WHERE o.protective = 0"
    ).fetchall()
    c.close()
    assert rows, "expected at least one strategy fill"
    sessions = [b.session.isoformat() for b in s.bars]
    for created, filled, ref in rows:
        i = sessions.index(created)
        assert filled == sessions[i + 1]
        assert Decimal(ref) == Decimal(repr(s.bars[i + 1].open))


def test_first_signal_is_long_on_uptrend():
    s = make_series([100 + i for i in range(25)])
    assert SmaTrend("SPY", 5, 20).signal(s, s.bars[-1].session).target is Target.LONG
