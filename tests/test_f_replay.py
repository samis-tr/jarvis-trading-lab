"""F. Replay is deterministic and auditable."""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal

import pytest

from jtl.errors import JournalCorrupt, SafetyError
from jtl.reconciliation import expected_from_fills
from jtl.simulator.engine import run_replay
from jtl.storage.db import Storage
from jtl.supervisor import Supervisor


def test_replay_is_byte_for_byte_deterministic(tmp_path, cfg, synth):
    a = run_replay(cfg, synth, tmp_path / "a.db")
    b = run_replay(cfg, synth, tmp_path / "b.db")
    assert a.journal_head == b.journal_head and a.final_equity == b.final_equity
    ca, cb = sqlite3.connect(tmp_path / "a.db"), sqlite3.connect(tmp_path / "b.db")
    q = "SELECT seq, ts, kind, payload, hash FROM events ORDER BY seq"
    assert ca.execute(q).fetchall() == cb.execute(q).fetchall()
    ca.close()
    cb.close()


def test_journal_reproduces_ledger(tmp_path, cfg, synth):
    r = run_replay(cfg, synth, tmp_path / "a.db")
    with Storage(tmp_path / "a.db") as st:
        fills = [e["payload"] for e in reversed(st.events(limit=100000, kind="fill"))]
        cash = Decimal(str(cfg.simulator.starting_cash))
        for f in fills:
            q, p, fee = Decimal(f["qty"]), Decimal(f["price"]), Decimal(f["fees"])
            cash += (-(q * p) - fee) if f["side"] == "buy" else (q * p - fee)
        exp_cash, _ = expected_from_fills(st, Decimal(str(cfg.simulator.starting_cash)))
        assert cash == exp_cash == Decimal(st.query("SELECT cash FROM account")[0][0])
        n, head = st.verify_journal()
    assert n == r.journal_events and head == r.journal_head and fills


def test_replay_refuses_existing_db(tmp_path, cfg, synth):
    run_replay(cfg, synth, tmp_path / "a.db")
    with pytest.raises(FileExistsError):
        run_replay(cfg, synth, tmp_path / "a.db")


def test_session_cannot_be_processed_twice(tmp_path, small_cfg):
    from tests.conftest import make_series

    s = make_series([100.0] * 25)
    with Storage(tmp_path / "x.db") as st:
        sup = Supervisor(small_cfg, st)
        sup.start(s.bars[0].session)
        sup.process_session(s.bars[0].session, s.upto(s.bars[0].session))
        r = sup.process_session(s.bars[0].session, s.upto(s.bars[0].session))
        assert r.blocked and sup.halted


def test_journal_is_immutable_and_tamper_evident(tmp_path, cfg, synth):
    run_replay(cfg, synth, tmp_path / "a.db")
    c = sqlite3.connect(tmp_path / "a.db")
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("UPDATE events SET payload='{}' WHERE seq=5")
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("DELETE FROM events WHERE seq=5")
    # an attacker drops the trigger and edits history -> detected on next open
    c.execute("DROP TRIGGER events_no_update")
    row = json.loads(c.execute("SELECT payload FROM events WHERE seq=3").fetchone()[0])
    row["tampered"] = True
    c.execute("UPDATE events SET payload=? WHERE seq=3", (json.dumps(row),))
    c.commit()
    c.close()
    with pytest.raises(JournalCorrupt):
        Storage(tmp_path / "a.db")


def test_journal_corruption_mid_run_halts(tmp_path, small_cfg):
    from tests.conftest import make_series

    s = make_series([100.0] * 25)
    with Storage(tmp_path / "x.db") as st:
        sup = Supervisor(small_cfg, st)
        sup.start(s.bars[0].session)
        sup.process_session(s.bars[0].session, s.upto(s.bars[0].session))
        st.conn.execute("DROP TRIGGER events_no_update")
        st.conn.execute("UPDATE events SET kind='x' WHERE seq=1")
        with pytest.raises(SafetyError):  # detected by the periodic FULL re-hash (every 20 sessions)
            for b in s.bars[1:]:
                sup.process_session(b.session, s.upto(b.session))
        assert sup.halted
        assert st.query("SELECT COUNT(*) FROM orders")[0][0] == 0


def test_journal_corruption_detected_before_any_order(tmp_path, small_cfg):
    from jtl.domain import OrderIntent, Side
    from tests.conftest import make_series

    s = make_series([100.0] * 3)
    with Storage(tmp_path / "y.db") as st:
        sup = Supervisor(small_cfg, st)
        sup.start(s.bars[0].session)
        st.conn.execute("DROP TRIGGER events_no_update")
        st.conn.execute("UPDATE events SET payload='{}' WHERE seq=1")
        i = OrderIntent(
            client_order_id="corrupt-test-1",
            symbol="SPY",
            side=Side.BUY,
            qty=Decimal("0.1"),
            created_session=s.bars[0].session,
        )
        with pytest.raises(JournalCorrupt):
            sup.submit(i, Decimal(100), "t")
        assert st.query("SELECT COUNT(*) FROM orders")[0][0] == 0 and sup.halted
