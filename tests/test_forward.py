"""Daily forward mode: start, catch-up, idempotency, stale data, intraday bars, data revisions."""

from __future__ import annotations

import datetime as dt
import sqlite3

import pytest

from jtl.errors import DataError
from jtl.market_data import calendar
from jtl.market_data.models import Bar, BarSeries
from jtl.simulator.forward import forward_step
from jtl.strategy import AlwaysLong, SmaTrend

BOTS = [SmaTrend("SPY", 5, 20), AlwaysLong("SPY")]


def after_close(s: dt.date, minutes: int = 90) -> dt.datetime:
    return calendar.session_close(s) + dt.timedelta(minutes=minutes)


def test_start_then_catch_up_then_idempotent(tmp_path, small_cfg, synth):
    day0 = synth.bars[300].session
    r0 = forward_step(small_cfg, synth.upto(day0), tmp_path, bots=BOTS, now=after_close(day0))
    assert all(b.started and b.processed == [day0.isoformat()] for b in r0.bots)
    assert r0.board["hypothetical"] is True and "FORWARD" in r0.board["period"]

    day5 = synth.bars[305].session  # PC was off for 5 sessions -> all caught up, in order
    r1 = forward_step(small_cfg, synth.upto(day5), tmp_path, bots=BOTS, now=after_close(day5))
    expected = [b.session.isoformat() for b in synth.bars[301:306]]
    assert all(b.processed == expected for b in r1.bots)

    r2 = forward_step(small_cfg, synth.upto(day5), tmp_path, bots=BOTS, now=after_close(day5, 300))
    assert all(b.processed == [] for b in r2.bots)  # second run the same evening changes nothing
    c = sqlite3.connect(tmp_path / "hold.db")
    assert c.execute("SELECT COUNT(*) FROM equity").fetchone()[0] == 6
    assert c.execute("SELECT COUNT(*) FROM breakers WHERE name='system_halt'").fetchone()[0] == 0
    c.close()


def test_hold_bot_buys_next_open_after_start(tmp_path, small_cfg, synth):
    day0, day1 = synth.bars[300].session, synth.bars[301].session
    forward_step(small_cfg, synth.upto(day0), tmp_path, bots=[AlwaysLong("SPY")], now=after_close(day0))
    forward_step(small_cfg, synth.upto(day1), tmp_path, bots=[AlwaysLong("SPY")], now=after_close(day1))
    c = sqlite3.connect(tmp_path / "hold.db")
    (sess,) = c.execute("SELECT session FROM fills").fetchone()
    cash0 = c.execute("SELECT payload FROM events WHERE kind='account_opened'").fetchone()[0]
    c.close()
    assert sess == day1.isoformat() and '"cash":"100' in cash0


def test_stale_data_does_nothing(tmp_path, small_cfg, synth):
    day0 = synth.bars[300].session
    with pytest.raises(DataError, match="stale"):
        forward_step(small_cfg, synth.upto(day0), tmp_path, bots=BOTS, now=after_close(day0) + dt.timedelta(days=4))
    assert not list(tmp_path.glob("*.db"))


def test_intraday_unfinished_bar_is_ignored(tmp_path, small_cfg, synth):
    day0, day1 = synth.bars[300].session, synth.bars[301].session
    during_day1 = calendar.session_open(day1) + dt.timedelta(hours=2)
    r = forward_step(small_cfg, synth.upto(day1), tmp_path, bots=BOTS, now=during_day1)
    assert r.latest_session == day0  # day1's partial bar was dropped


def test_data_revision_halts_bot(tmp_path, small_cfg, synth):
    day0, day1 = synth.bars[300].session, synth.bars[301].session
    forward_step(small_cfg, synth.upto(day0), tmp_path, bots=BOTS, now=after_close(day0))
    revised = BarSeries(
        symbol="SPY",
        provenance=synth.provenance,
        bars=tuple(
            Bar(session=b.session, open=b.open / 2, high=b.high / 2, low=b.low / 2, close=b.close / 2, volume=b.volume)
            for b in synth.bars[:302]
        ),
    )
    r = forward_step(small_cfg, revised, tmp_path, bots=BOTS, now=after_close(day1))
    assert all(b.submitted == [] for b in r.bots)
    assert all(row["halted"] for row in r.board["bots"])
