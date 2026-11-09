"""Storage (migrations, single writer, backups), research split discipline, scheduler, reconciliation."""

from __future__ import annotations

import datetime as dt
import sqlite3
from decimal import Decimal

import pytest

from jtl import research
from jtl.errors import InsufficientData, ReconciliationMismatch, SafetyError, StorageLocked
from jtl.market_data import calendar
from jtl.reconciliation import reconcile
from jtl.scheduler import next_run_time
from jtl.simulator.broker import AccountView, LocalSimBroker
from jtl.simulator.costs import CostModel
from jtl.storage.db import Storage
from jtl.supervisor import Supervisor
from tests.conftest import make_series


def test_migrations_idempotent(tmp_path):
    for _ in range(2):
        with Storage(tmp_path / "m.db") as st:
            assert st.schema_version == 1


def test_single_writer_lock(tmp_path):
    with Storage(tmp_path / "w.db"), pytest.raises(StorageLocked):
        Storage(tmp_path / "w.db")
    with Storage(tmp_path / "w.db"):  # released after close
        pass


def test_backup_is_verified_copy(tmp_path, storage):
    storage.record("t", "hello", {"a": 1})
    p = storage.backup(tmp_path / "bk", label="x")
    c = sqlite3.connect(p)
    assert c.execute("SELECT kind FROM events").fetchall() == [("hello",)]
    c.close()


def test_one_pending_order_per_symbol_enforced_by_db(storage):
    storage.conn.execute("INSERT INTO orders VALUES ('a1234567','SPY','buy','1','pending','2024-01-02',0,'{}','')")
    with pytest.raises(sqlite3.IntegrityError):
        storage.conn.execute("INSERT INTO orders VALUES ('b1234567','SPY','buy','1','pending','2024-01-02',0,'{}','')")


def test_research_split_and_sealed_holdout(synth):
    ins, hold = research.split(synth, holdout_fraction=0.2, min_years=3)
    assert ins.series.bars[-1].session < hold.first_session
    with pytest.raises(SafetyError):
        research.select_parameters(synth, [(5, 20)], lambda s, f, sl: 0.0)  # raw series, not InSample
    seen = []
    best = research.select_parameters(ins, [(5, 20), (10, 30)], lambda s, f, sl: seen.append(s.bars[-1].session) or f)
    assert best == (10, 30) and max(seen) < hold.first_session
    hold.open_for_final_evaluation("final OOS check of chosen params")
    with pytest.raises(SafetyError):
        hold.open_for_final_evaluation("again, to peek at results")


def test_research_requires_five_years(synth):
    with pytest.raises(InsufficientData):
        research.split(synth, holdout_fraction=0.2, min_years=5)  # fixture spans ~4 years


def test_scheduler_runs_after_confirmed_close():
    t = next_run_time(dt.datetime(2024, 11, 29, 12, 0, tzinfo=calendar.NY), 60)
    assert (t.hour, t.minute) == (14, 0)  # early close 13:00 + 60 min
    t = next_run_time(dt.datetime(2024, 12, 24, 23, 0, tzinfo=calendar.NY), 60)
    assert t.date() == dt.date(2024, 12, 26)


def test_reconcile_detects_mismatch_and_margin(storage):
    with pytest.raises(ReconciliationMismatch):
        reconcile(
            storage,
            starting_cash=Decimal(1000),
            reported_cash=Decimal(1001),
            reported_buying_power=Decimal(1001),
            reported_positions={},
        )
    with pytest.raises(ReconciliationMismatch):
        reconcile(
            storage,
            starting_cash=Decimal(1000),
            reported_cash=Decimal(1000),
            reported_buying_power=Decimal(2000),
            reported_positions={},
        )
    reconcile(
        storage,
        starting_cash=Decimal(1000),
        reported_cash=Decimal(1000),
        reported_buying_power=Decimal(1000),
        reported_positions={},
    )


class MarginBroker(LocalSimBroker):
    def account(self) -> AccountView:
        a = super().account()
        return AccountView(
            cash=a.cash, buying_power=a.cash * 4, positions=a.positions, stops=a.stops, avg_cost=a.avg_cost
        )


def test_unexpected_buying_power_halts_supervisor(storage, small_cfg):
    s = make_series([100 + i for i in range(25)])
    broker = MarginBroker(storage, CostModel(small_cfg.simulator), 0.05)
    sup = Supervisor(small_cfg, storage, broker=broker)
    sup.start(s.bars[0].session)
    for b in s.bars:
        r = sup.process_session(b.session, s.upto(b.session))
        assert not r.submitted
    assert sup.halted
    assert storage.query("SELECT COUNT(*) FROM orders")[0][0] == 0
