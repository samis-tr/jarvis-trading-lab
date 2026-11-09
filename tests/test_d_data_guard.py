"""D. Bad, delayed or missing data prevents orders."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from jtl.errors import DataError, InsufficientData
from jtl.market_data import calendar
from jtl.market_data.models import Bar, BarSeries
from jtl.market_data.validation import check_fresh, check_sufficient, validate_series
from jtl.simulator.engine import run_replay
from tests.conftest import TEST_PROV, make_series

NY = ZoneInfo("America/New_York")


def _v(series, cfg):
    return validate_series(series, allowlist=cfg.symbols, max_abs_daily_return=cfg.data.max_abs_daily_return)


def test_missing_session_detected(cfg):
    s = make_series([100.0] * 30)
    gapped = BarSeries(symbol="SPY", provenance=TEST_PROV, bars=s.bars[:10] + s.bars[11:])
    rep = _v(gapped, cfg)
    assert any(i.kind == "missing" for i in rep.issues)
    with pytest.raises(DataError):
        rep.raise_if_bad()


def test_anomaly_duplicate_ohlc_nonsession_detected(cfg):
    s = make_series([100.0] * 10 + [130.0] + [130.0] * 5)
    assert any(i.kind == "anomaly" for i in _v(s, cfg).issues)
    dup = BarSeries(symbol="SPY", provenance=TEST_PROV, bars=(*s.bars[:5], s.bars[4], *s.bars[5:]))
    assert any(i.kind == "duplicate" for i in _v(dup, cfg).issues)
    weekend = Bar(session=dt.date(2021, 1, 9), open=100, high=101, low=99, close=100, volume=1)
    ws = BarSeries(symbol="SPY", provenance=TEST_PROV, bars=(s.bars[0], weekend))
    assert any(i.kind == "not_session" for i in _v(ws, cfg).issues)
    bad = Bar(session=s.bars[1].session, open=100, high=99, low=98, close=100, volume=1)
    assert any(
        i.kind == "ohlc" for i in _v(BarSeries(symbol="SPY", provenance=TEST_PROV, bars=(s.bars[0], bad)), cfg).issues
    )


def test_non_allowlisted_symbol_refused(cfg):
    with pytest.raises(DataError):
        _v(make_series([1.0] * 3, symbol="TSLA"), cfg)


def test_stale_and_unconfirmed_bars_refused():
    s = make_series([100.0] * 20, start=dt.date(2024, 2, 1))
    last = s.bars[-1].session
    close = calendar.session_close(last)
    check_fresh(s, close + dt.timedelta(minutes=61), 60)  # fresh and confirmed
    with pytest.raises(DataError, match="not yet confirmed"):
        check_fresh(s, close + dt.timedelta(minutes=10), 60)  # bar exists but session not confirmed
    with pytest.raises(DataError, match="stale"):
        check_fresh(s, close + dt.timedelta(days=3), 60)


def test_naive_or_wrong_timezone_refused():
    with pytest.raises(DataError):
        calendar.latest_confirmed_session(dt.datetime(2024, 3, 5, 20, 0), 60)  # naive
    with pytest.raises(DataError):
        calendar.session_from_timestamp(dt.datetime(2024, 3, 5, 0, 0))  # naive
    with pytest.raises(DataError):  # midnight UTC is 19:00 NY the day before -> not a NY-midnight stamp
        calendar.session_from_timestamp(dt.datetime(2024, 3, 5, 0, 0, tzinfo=dt.UTC))
    assert calendar.session_from_timestamp(dt.datetime(2024, 3, 5, 5, 0, tzinfo=dt.UTC)) == dt.date(2024, 3, 5)


def test_early_close_and_holidays():
    assert not calendar.is_session(dt.date(2024, 12, 25))
    assert calendar.session_close(dt.date(2024, 11, 29)).hour == 13  # day after Thanksgiving


def test_insufficient_history_reported():
    with pytest.raises(InsufficientData):
        check_sufficient(make_series([100.0] * 300), 5)


def test_replay_halts_and_places_no_orders_after_bad_data(tmp_path, small_cfg):
    closes = [100 + i * 0.3 for i in range(60)]
    s = make_series(closes)
    # remove a bar after warm-up and before any position could exist -> missing session
    gapped = BarSeries(symbol="SPY", provenance=TEST_PROV, bars=s.bars[:15] + s.bars[16:])
    r = run_replay(small_cfg, gapped, tmp_path / "g.db")
    assert r.halted
    assert not any(x.submitted for x in r.results[15:])
    import sqlite3

    c = sqlite3.connect(tmp_path / "g.db")
    assert (
        c.execute(
            "SELECT COUNT(*) FROM orders WHERE created_session >= ?", (s.bars[15].session.isoformat(),)
        ).fetchone()[0]
        == 0
    )
    assert c.execute("SELECT COUNT(*) FROM events WHERE kind='orders_blocked'").fetchone()[0] > 0
    c.close()


def test_price_anomaly_halts_replay(tmp_path, small_cfg):
    closes = [100 + i * 0.3 for i in range(40)]
    closes[30] = closes[29] * 1.4
    r = run_replay(small_cfg, make_series(closes), tmp_path / "a.db")
    assert r.halted and not any(x.submitted for x in r.results[30:])
