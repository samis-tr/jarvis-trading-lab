"""Shared fixtures. No network, no API keys: everything is mocked or synthetic (labelled TEST)."""

from __future__ import annotations

import datetime as dt
import socket

import pytest

from jtl.config import AppConfig, load_config
from jtl.market_data import calendar
from jtl.market_data.models import Adjustment, Bar, BarSeries, Provenance, Source
from jtl.market_data.sample import synthetic_pair
from jtl.storage.db import Storage

TEST_PROV = Provenance(source=Source.TEST, adjustment=Adjustment.SPLIT, note="unit test fixture")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Any non-loopback socket connection during tests is a bug (loopback is needed by asyncio on Windows)."""
    real_connect = socket.socket.connect

    def guard(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host in ("127.0.0.1", "::1", "localhost"):
            return real_connect(self, address, *a, **k)
        raise RuntimeError(f"real network access attempted during tests: {address!r}")

    def no_create(*a, **k):
        raise RuntimeError("real network access attempted during tests")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", no_create)
    monkeypatch.setenv("JTL_NO_USER_ENV", "1")  # never pick up the real user's keys in tests
    for v in ("APCA_API_BASE_URL", "ALPACA_BASE_URL", "APCA_API_KEY_ID", "APCA_API_SECRET_KEY"):
        monkeypatch.delenv(v, raising=False)


@pytest.fixture
def cfg() -> AppConfig:
    return load_config(data={}, environ={})


@pytest.fixture
def small_cfg() -> AppConfig:
    return load_config(data={"strategy": {"fast_window": 5, "slow_window": 20}}, environ={})


@pytest.fixture
def storage(tmp_path):
    st = Storage(tmp_path / "t.db")
    yield st
    st.close()


@pytest.fixture(scope="session")
def synth() -> BarSeries:
    price, _ = synthetic_pair("SPY", start=dt.date(2017, 1, 3), end=dt.date(2020, 12, 31), seed=11, source=Source.TEST)
    return price


def make_series(
    closes: list[float],
    start: dt.date = dt.date(2021, 1, 4),
    *,
    opens: list[float] | None = None,
    lows: list[float] | None = None,
    symbol: str = "SPY",
) -> BarSeries:
    sessions = calendar.sessions_in_range(start, start + dt.timedelta(days=len(closes) * 2 + 30))[: len(closes)]
    bars = []
    for i, (s, c) in enumerate(zip(sessions, closes, strict=True)):
        o = opens[i] if opens else c
        lo = lows[i] if lows else min(o, c) * 0.995
        bars.append(Bar(session=s, open=o, high=max(o, c) * 1.005, low=min(lo, o, c), close=c, volume=1e6))
    return BarSeries(symbol=symbol, provenance=TEST_PROV, bars=tuple(bars))
