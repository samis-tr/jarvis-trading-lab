"""Live price view: display only, guarded host, cached, failure-tolerant, never trades."""

from __future__ import annotations

import datetime as dt
import sqlite3

import httpx
from fastapi.testclient import TestClient

from jtl.dashboard import create_app
from jtl.market_data import calendar
from jtl.market_data.live import LivePrice, market_open_now
from jtl.simulator.forward import forward_step
from jtl.strategy import AlwaysLong


def _live(handler, monkeypatch) -> LivePrice:
    monkeypatch.setenv("APCA_API_KEY_ID", "PKTEST0000")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "SECRETTEST0000")
    return LivePrice("SPY", transport=httpx.MockTransport(handler))


def test_quote_fetch_is_guarded_and_cached(monkeypatch):
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(200, json={"symbol": "SPY", "trade": {"t": "2026-11-09T15:00:01Z", "p": 701.25}})

    lp = _live(handler, monkeypatch)
    q1, err = lp.get()
    q2, _ = lp.get()
    assert err == "" and q1.price == 701.25 and q2 is q1
    assert len(calls) == 1 and calls[0].startswith("https://data.alpaca.markets/v2/stocks/SPY/trades/latest")


def test_quote_failures_never_raise(monkeypatch):
    def boom(req):
        raise httpx.ConnectError("down")

    assert _live(boom, monkeypatch).get()[0] is None
    assert _live(lambda r: httpx.Response(403), monkeypatch).get() == (None, "HTTP 403")
    monkeypatch.delenv("APCA_API_KEY_ID")
    assert LivePrice("SPY").get() == (None, "no keys")


def test_market_open_now():
    s = dt.date(2026, 11, 6)
    assert market_open_now(calendar.session_open(s) + dt.timedelta(hours=1))
    assert not market_open_now(calendar.session_close(s) + dt.timedelta(minutes=1))
    assert not market_open_now(dt.datetime(2026, 11, 8, 17, 0, tzinfo=dt.UTC))  # Sunday


def test_live_endpoint_values_bots_and_never_changes_ledger(tmp_path, small_cfg, synth, monkeypatch):
    d0, d1 = synth.bars[300].session, synth.bars[301].session
    after = calendar.session_close(d1) + dt.timedelta(minutes=90)
    forward_step(
        small_cfg,
        synth.upto(d0),
        tmp_path,
        bots=[AlwaysLong("SPY")],
        now=calendar.session_close(d0) + dt.timedelta(minutes=90),
    )
    forward_step(small_cfg, synth.upto(d1), tmp_path, bots=[AlwaysLong("SPY")], now=after)
    before = sqlite3.connect(tmp_path / "hold.db").execute("SELECT COUNT(*) FROM events").fetchone()[0]
    last_close = synth.bars[301].close
    lp = _live(
        lambda r: httpx.Response(200, json={"trade": {"t": "2026-11-09T15:00:01Z", "p": last_close * 1.01}}),
        monkeypatch,
    )
    c = TestClient(create_app(None, tmp_path, lp))
    d = c.get("/api/live").json()
    assert d["ok"] and d["hypothetical"] is True and d["bots"]["hold"]["live"]
    assert d["bots"]["hold"]["value"] > 0
    assert c.post("/api/live").status_code == 405
    after_events = sqlite3.connect(tmp_path / "hold.db").execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert after_events == before  # display only: nothing written
    assert "/api/live" in c.get("/").text


def test_absurd_live_price_is_ignored(tmp_path, small_cfg, synth, monkeypatch):
    d0 = synth.bars[300].session
    forward_step(
        small_cfg,
        synth.upto(d0),
        tmp_path,
        bots=[AlwaysLong("SPY")],
        now=calendar.session_close(d0) + dt.timedelta(minutes=90),
    )
    lp = _live(lambda r: httpx.Response(200, json={"trade": {"t": "2026-11-09T15:00:01Z", "p": 1.0}}), monkeypatch)
    d = TestClient(create_app(None, tmp_path, lp)).get("/api/live").json()
    assert not d["ok"] and "wrong" in d["reason"]
