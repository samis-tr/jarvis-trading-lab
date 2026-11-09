"""B. Risk violations are blocked, including combined exposure and concurrent duplicates."""

from __future__ import annotations

import datetime as dt
import threading
from decimal import Decimal

import pytest
from pydantic import ValidationError

from jtl.domain import OrderIntent, Side
from jtl.errors import OrderRejected
from jtl.risk.breakers import Breaker
from jtl.risk.engine import PendingOrder, RiskEngine, Snapshot
from jtl.simulator.broker import LocalSimBroker
from jtl.simulator.costs import CostModel
from jtl.supervisor import Supervisor

S = dt.date(2024, 3, 4)
PX = Decimal("100")


def snap(**kw) -> Snapshot:
    base = dict(
        session=S,
        cash=Decimal(1000),
        buying_power=Decimal(1000),
        equity=Decimal(1000),
        positions={},
        prices={"SPY": PX},
    )
    base.update(kw)
    return Snapshot(**base)


def intent(qty="0.5", side=Side.BUY, oid="test-order-0001", sym="SPY") -> OrderIntent:
    return OrderIntent(client_order_id=oid, symbol=sym, side=side, qty=Decimal(qty), created_session=S)


@pytest.fixture
def engine(cfg) -> RiskEngine:
    return RiskEngine(cfg.risk, cfg.symbols, entry_buffer_pct=0.03, est_cost_bps=11)


def test_risk_budget_per_trade(engine):
    # 0.5% of 1000 = $5 risk; stop 5% of $100 = $5/share -> max 1 share by risk; 20% cap -> ~1.94 shares
    assert engine.evaluate(intent("0.9"), snap()).approved
    d = engine.evaluate(intent("1.1"), snap())
    assert not d.approved and any("trade risk" in r for r in d.reasons)


def test_position_cap_20pct(cfg):
    loose_stop = cfg.risk.model_copy(update={"stop_loss_pct": 0.01})
    e = RiskEngine(loose_stop, cfg.symbols)
    d = e.evaluate(intent("2.5"), snap())
    assert not d.approved and any("combined exposure" in r for r in d.reasons)


def test_combined_exposure_counts_existing_position_and_pending(cfg):
    e = RiskEngine(cfg.risk.model_copy(update={"stop_loss_pct": 0.01}), cfg.symbols)
    # Holding 1.5 shares ($150) + new 0.6 ($60) > $200 cap (after buffer)
    d = e.evaluate(intent("0.6"), snap(positions={"SPY": Decimal("1.5")}, cash=Decimal(850), buying_power=Decimal(850)))
    assert not d.approved and any("combined exposure" in r for r in d.reasons)
    assert e.max_buy_qty(snap(positions={"SPY": Decimal("1.5")}), "SPY") < Decimal("0.5")


def test_concurrent_pending_duplicate_rejected(engine):
    p = (PendingOrder("other-order-01", "SPY", Side.BUY, Decimal("0.2")),)
    d = engine.evaluate(intent("0.2"), snap(pending=p))
    assert not d.approved and any("concurrent" in r for r in d.reasons)


def test_duplicate_order_id_rejected(engine):
    d = engine.evaluate(intent(), snap(known_order_ids=frozenset({"test-order-0001"})))
    assert not d.approved and "duplicate client_order_id" in d.reasons


def test_cash_only_and_no_shorting(engine):
    d = engine.evaluate(intent("0.5"), snap(cash=Decimal(20), buying_power=Decimal(20)))
    assert not d.approved and any("insufficient cash" in r for r in d.reasons)
    d = engine.evaluate(intent("1", side=Side.SELL), snap())
    assert not d.approved and any("shorting" in r for r in d.reasons)


def test_unexpected_buying_power_rejected(engine):
    d = engine.evaluate(intent("0.1"), snap(buying_power=Decimal(4000)))
    assert not d.approved and any("buying power" in r for r in d.reasons)


def test_symbol_allowlist_and_order_limits(engine):
    assert not engine.evaluate(intent(sym="TSLA"), snap()).approved
    assert not engine.evaluate(intent("0.1"), snap(orders_today=2)).approved


def test_breaker_blocks_buys_but_allows_risk_reducing_sells(engine):
    b = (Breaker("drawdown", True, "dd", S, None),)
    assert not engine.evaluate(intent("0.1"), snap(active_breakers=b)).approved
    sell = intent("0.5", side=Side.SELL, oid="test-sell-0001")
    assert engine.evaluate(sell, snap(positions={"SPY": Decimal("0.5")}, active_breakers=b)).approved


def test_typed_intent_rejects_dangerous_fields():
    for extra in (
        {"leverage": 2},
        {"asset_class": "option"},
        {"side": "short"},
        {"time_in_force": "gtc"},
        {"qty": Decimal("-1")},
        {"base_url": "https://api.alpaca.markets"},
    ):
        data = dict(client_order_id="abcdefgh1", symbol="SPY", side="buy", qty="1", created_session=S)
        data.update(extra)
        with pytest.raises(ValidationError):
            OrderIntent.model_validate(data)


def test_concurrent_duplicate_submissions_only_one_accepted(storage, cfg):
    broker = LocalSimBroker(storage, CostModel(cfg.simulator), 0.05)
    broker.open_account(Decimal(1000), "2024-03-04T09:30:00-05:00")
    results: list[str] = []

    def go(i: int) -> None:
        try:
            broker.submit(intent("0.3", oid=f"concurrent-{i:04d}"), "2024-03-04T17:00:00-05:00")
            results.append("ok")
        except OrderRejected:
            results.append("rejected")

    threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1 and results.count("rejected") == 7
    assert len(broker.pending()) == 1


def test_retry_with_same_id_is_idempotent(storage, cfg):
    broker = LocalSimBroker(storage, CostModel(cfg.simulator), 0.05)
    broker.open_account(Decimal(1000), "t0")
    o1 = broker.submit(intent("0.3"), "t1")
    o2 = broker.submit(intent("0.3"), "t2")
    assert o1.intent == o2.intent and len(broker.pending()) == 1
    assert storage.query("SELECT COUNT(*) FROM events WHERE kind='order_accepted'")[0][0] == 1
    with pytest.raises(OrderRejected):
        broker.submit(intent("0.4"), "t3")  # same ID, different params


def test_supervisor_submit_is_the_only_path_and_enforces_risk(storage, cfg):
    sup = Supervisor(cfg, storage)
    sup.start(S)
    assert not sup.submit(intent("5"), PX, "ts")  # way over limits
    assert storage.query("SELECT COUNT(*) FROM orders")[0][0] == 0
    assert sup.submit(intent("0.5"), PX, "ts")
