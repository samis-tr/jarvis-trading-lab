"""C. Breakers survive restart; latched breakers never auto-reset; loss pauses trip correctly."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from jtl.errors import SafetyError
from jtl.risk.breakers import RESET_PHRASE, BreakerBook
from jtl.storage.db import Storage
from jtl.supervisor import Supervisor
from tests.conftest import make_series

S = dt.date(2024, 3, 4)


def test_latched_drawdown_survives_restart_and_never_auto_resets(tmp_path):
    db = tmp_path / "b.db"
    with Storage(db) as st:
        BreakerBook(st).trip("drawdown", "dd -5.1%", S, None, "t")
    for _ in range(3):  # several "restarts", far in the future
        with Storage(db) as st:
            active = BreakerBook(st).active(dt.date(2030, 1, 2))
            assert [b.name for b in active] == ["drawdown"] and active[0].latched


def test_trip_cannot_overwrite_latched_breaker(storage):
    bb = BreakerBook(storage)
    bb.trip("system_halt", "journal mismatch", S, None, "t1")
    bb.trip("system_halt", "something else", S + dt.timedelta(days=5), dt.date(2024, 3, 5), "t2")
    (b,) = bb.all()
    assert b.reason == "journal mismatch" and b.latched and b.until_session is None


def test_manual_reset_needs_exact_phrase_and_operator(storage):
    bb = BreakerBook(storage)
    bb.trip("drawdown", "dd", S, None, "t")
    with pytest.raises(SafetyError):
        bb.manual_reset("drawdown", "yes", "me", "t")
    with pytest.raises(SafetyError):
        bb.manual_reset("drawdown", RESET_PHRASE, " ", "t")
    bb.manual_reset("drawdown", RESET_PHRASE, "operator-1", "t")
    assert bb.all() == []
    assert storage.events(kind="breaker_manual_reset")


def test_pauses_expire_but_drawdown_does_not(storage):
    bb = BreakerBook(storage)
    bb.trip("daily_loss", "-1.2%", S, dt.date(2024, 3, 5), "t")
    assert bb.active(dt.date(2024, 3, 5)) and not bb.active(dt.date(2024, 3, 6))


def _run(sup: Supervisor, series, upto: int | None = None):
    out = []
    for b in series.bars[:upto]:
        view = series.upto(b.session)
        out.append(sup.process_session(b.session, view))
    return out


def test_supervisor_trips_daily_weekly_and_drawdown(tmp_path, small_cfg):
    # uptrend so the strategy buys, then a crash day
    closes = [100 + i * 0.5 for i in range(40)] + [100 + 39 * 0.5] * 3
    opens = list(closes)
    series = make_series(closes, opens=opens)
    db = tmp_path / "s.db"
    with Storage(db) as st:
        sup = Supervisor(small_cfg, st)
        sup.start(series.bars[0].session)
        _run(sup, series)
        assert st.query("SELECT COUNT(*) FROM positions")[0][0] == 1  # strategy is long before the crash
    crash = make_series([*closes, 40.0, 40.0], opens=[*opens, 40.0, 40.0])
    with Storage(db) as st:
        sup = Supervisor(small_cfg, st)
        for b in crash.bars[len(closes) :]:
            sup.process_session(b.session, crash.upto(b.session), bad_sessions=frozenset())
        names = {b.name for b in BreakerBook(st).all()}
    assert {"daily_loss", "weekly_loss", "drawdown"} <= names
    with Storage(db) as st:  # restart: still blocked
        assert BreakerBook(st).is_latched()


def test_drawdown_from_peak_latches_and_blocks_new_buys(tmp_path, small_cfg):
    db = tmp_path / "d.db"
    with Storage(db) as st:
        sup = Supervisor(small_cfg, st)
        sup.start(S)
        st.record("t", "test", {})
        with st.tx() as c:
            st.kv_set(c, "peak_equity", "1100")
        sup._update_breakers(S, Decimal("1040"))  # -5.45% from peak
    with Storage(db) as st:
        sup = Supervisor(small_cfg, st)
        assert any(b.name == "drawdown" and b.latched for b in sup.breakers.all())
        from jtl.domain import OrderIntent, Side

        i = OrderIntent(
            client_order_id="after-restart-1",
            symbol="SPY",
            side=Side.BUY,
            qty=Decimal("0.1"),
            created_session=dt.date(2024, 3, 11),
        )
        assert not sup.submit(i, Decimal(100), "t")
