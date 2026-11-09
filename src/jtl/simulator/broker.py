"""LocalSimBroker - a persistent local paper ledger (USD, cash-only, long-only). No network at all.

* Idempotent client order IDs: re-submitting an existing ID returns the original order, never a duplicate.
* At most one pending order per symbol (enforced in Python AND by a partial UNIQUE index).
* Every state change is written together with an immutable journal event in one transaction.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from dataclasses import dataclass
from decimal import Decimal

from jtl.domain import Fill, Order, OrderIntent, OrderStatus, Side, d
from jtl.errors import OrderRejected, SafetyError
from jtl.market_data.models import Bar
from jtl.risk.engine import PendingOrder
from jtl.simulator.costs import CostModel
from jtl.storage import journal
from jtl.storage.db import Storage


@dataclass(frozen=True)
class AccountView:
    cash: Decimal
    buying_power: Decimal
    positions: dict[str, Decimal]
    stops: dict[str, Decimal | None]
    avg_cost: dict[str, Decimal]


class LocalSimBroker:
    name = "local_sim"

    def __init__(self, storage: Storage, costs: CostModel, stop_loss_pct: float):
        self.storage = storage
        self.costs = costs
        self.stop_pct = d(stop_loss_pct)
        self._submit_lock = threading.Lock()

    # -- account ---------------------------------------------------------------------------------
    def open_account(self, starting_cash: Decimal, ts: str) -> None:
        with self.storage.tx() as c:
            if c.execute("SELECT 1 FROM account").fetchone():
                return
            c.execute("INSERT INTO account(id, cash) VALUES (1, ?)", (str(starting_cash),))
            journal.append(c, ts, "account_opened", {"cash": starting_cash, "currency": "USD", "broker": self.name})

    def account(self) -> AccountView:
        row = self.storage.query("SELECT cash FROM account WHERE id = 1")
        if not row:
            raise SafetyError("account not opened")
        cash = Decimal(row[0][0])
        pos, stops, avg = {}, {}, {}
        for sym, q, a, s in self.storage.query("SELECT symbol, qty, avg_cost, stop_price FROM positions"):
            pos[sym], avg[sym] = Decimal(q), Decimal(a)
            stops[sym] = Decimal(s) if s else None
        return AccountView(cash=cash, buying_power=cash, positions=pos, stops=stops, avg_cost=avg)

    def pending(self) -> tuple[PendingOrder, ...]:
        rows = self.storage.query(
            "SELECT client_order_id, symbol, side, qty FROM orders WHERE status = 'pending' ORDER BY rowid"
        )
        return tuple(PendingOrder(i, s, Side(sd), Decimal(q)) for i, s, sd, q in rows)

    def order_ids(self) -> frozenset[str]:
        return frozenset(r[0] for r in self.storage.query("SELECT client_order_id FROM orders"))

    def orders_on(self, session: dt.date) -> int:
        return self.storage.query(
            "SELECT COUNT(*) FROM orders WHERE created_session = ? AND protective = 0", (session.isoformat(),)
        )[0][0]

    def get_order(self, client_order_id: str) -> Order | None:
        r = self.storage.query("SELECT intent, status FROM orders WHERE client_order_id = ?", (client_order_id,))
        if not r:
            return None
        return Order(intent=OrderIntent.model_validate_json(r[0][0]), status=OrderStatus(r[0][1]))

    # -- submission ------------------------------------------------------------------------------
    def submit(self, intent: OrderIntent, ts: str) -> Order:
        """Accept a risk-approved intent as PENDING (fills at the next session open). Idempotent."""
        with self._submit_lock:
            existing = self.get_order(intent.client_order_id)
            if existing is not None:
                if existing.intent != intent:
                    raise OrderRejected("client_order_id reused with different parameters")
                return existing
            with self.storage.tx() as c:
                if c.execute(
                    "SELECT 1 FROM orders WHERE symbol = ? AND status = 'pending'", (intent.symbol,)
                ).fetchone():
                    raise OrderRejected(f"concurrent pending order for {intent.symbol}")
                c.execute(
                    "INSERT INTO orders(client_order_id, symbol, side, qty, status, created_session, protective, "
                    "intent, reason) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        intent.client_order_id,
                        intent.symbol,
                        intent.side.value,
                        str(intent.qty),
                        "pending",
                        intent.created_session.isoformat(),
                        int(intent.is_protective_exit),
                        intent.model_dump_json(),
                        intent.reason,
                    ),
                )
                journal.append(c, ts, "order_accepted", {"intent": intent.model_dump(mode="json")})
            return Order(intent=intent, status=OrderStatus.PENDING)

    # -- execution -------------------------------------------------------------------------------
    def fill_pending(self, session: dt.date, bars: dict[str, Bar], ts: dt.datetime) -> list[Fill]:
        fills: list[Fill] = []
        rows = self.storage.query(
            "SELECT intent FROM orders WHERE status = 'pending' AND created_session < ? ORDER BY rowid",
            (session.isoformat(),),
        )
        for (raw,) in rows:
            intent = OrderIntent.model_validate_json(raw)
            bar = bars.get(intent.symbol)
            if bar is None:
                self._cancel(intent, "no bar for fill session", ts)
                continue
            ref = d(bar.open)
            f = self._execute(
                intent.client_order_id,
                intent.symbol,
                intent.side,
                intent.qty,
                ref,
                session,
                ts,
                "open",
                order_intent=intent,
            )
            if f:
                fills.append(f)
        return fills

    def check_stops(self, session: dt.date, bars: dict[str, Bar], ts: dt.datetime) -> list[Fill]:
        """Protective stops: gapped-through stops fill at the open (loss can exceed the modelled limit)."""
        fills: list[Fill] = []
        acct = self.account()
        for sym, qty in sorted(acct.positions.items()):
            stop = acct.stops.get(sym)
            bar = bars.get(sym)
            if qty <= 0 or stop is None or bar is None:
                continue
            o, lo = d(bar.open), d(bar.low)
            if o <= stop:
                ref, kind = o, "stop_gap"
            elif lo <= stop:
                ref, kind = stop, "stop"
            else:
                continue
            oid = f"stop-{sym}-{session:%Y%m%d}"
            intent = OrderIntent(
                client_order_id=oid,
                symbol=sym,
                side=Side.SELL,
                qty=qty,
                created_session=session,
                reason=f"protective {kind}",
                is_protective_exit=True,
            )
            with self.storage.tx() as c:
                if c.execute("SELECT 1 FROM orders WHERE client_order_id = ?", (oid,)).fetchone():
                    continue
                c.execute(
                    "INSERT INTO orders(client_order_id, symbol, side, qty, status, created_session, protective, "
                    "intent, reason) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        oid,
                        sym,
                        "sell",
                        str(qty),
                        "pending",
                        session.isoformat(),
                        1,
                        intent.model_dump_json(),
                        intent.reason,
                    ),
                )
                journal.append(c, ts.isoformat(), "order_accepted", {"intent": intent.model_dump(mode="json")})
            f = self._execute(oid, sym, Side.SELL, qty, ref, session, ts, kind, order_intent=intent)
            if f:
                fills.append(f)
        return fills

    def _cancel(self, intent: OrderIntent, reason: str, ts: dt.datetime) -> None:
        with self.storage.tx() as c:
            c.execute(
                "UPDATE orders SET status='cancelled', reason=? WHERE client_order_id=?",
                (reason, intent.client_order_id),
            )
            journal.append(
                c, ts.isoformat(), "order_cancelled", {"client_order_id": intent.client_order_id, "reason": reason}
            )

    def _execute(
        self,
        oid: str,
        sym: str,
        side: Side,
        qty: Decimal,
        ref: Decimal,
        session: dt.date,
        open_ts: dt.datetime,
        kind: str,
        order_intent: OrderIntent,
    ) -> Fill | None:
        price = self.costs.fill_price(side, ref)
        fees = self.costs.fees(side, qty, price)
        fill_ts = self.costs.fill_time(open_ts)
        acct = self.account()
        held = acct.positions.get(sym, Decimal(0))
        if side is Side.BUY:
            cost = qty * price + fees
            if cost > acct.cash:
                self._cancel(order_intent, "insufficient cash at fill (gap up)", fill_ts)
                return None
            new_cash = acct.cash - cost
            new_qty = held + qty
            new_avg = ((acct.avg_cost.get(sym, Decimal(0)) * held) + qty * price) / new_qty
            stop = (price * (1 - self.stop_pct)).quantize(Decimal("0.0001"))
        else:
            if qty > held:
                self._cancel(order_intent, "sell exceeds position", fill_ts)
                return None
            new_cash = acct.cash + qty * price - fees
            new_qty = held - qty
            new_avg = acct.avg_cost.get(sym, Decimal(0))
            stop = acct.stops.get(sym)
        fill = Fill(
            client_order_id=oid,
            symbol=sym,
            side=side,
            qty=qty,
            price=price,
            reference_price=ref,
            fees=fees,
            session=session,
            timestamp=fill_ts,
            kind=kind,
        )
        with self.storage.tx() as c:
            c.execute("UPDATE account SET cash = ? WHERE id = 1", (str(new_cash),))
            if new_qty > 0:
                c.execute(
                    "INSERT INTO positions(symbol, qty, avg_cost, stop_price) VALUES (?,?,?,?) ON CONFLICT(symbol) "
                    "DO UPDATE SET qty=excluded.qty, avg_cost=excluded.avg_cost, stop_price=excluded.stop_price",
                    (sym, str(new_qty), str(new_avg.quantize(Decimal("0.000001"))), str(stop) if stop else None),
                )
            else:
                c.execute("DELETE FROM positions WHERE symbol = ?", (sym,))
            c.execute("UPDATE orders SET status='filled' WHERE client_order_id = ?", (oid,))
            c.execute(
                "INSERT INTO fills(client_order_id, symbol, side, qty, price, reference_price, fees, session, ts, kind)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    oid,
                    sym,
                    side.value,
                    str(qty),
                    str(price),
                    str(ref),
                    str(fees),
                    session.isoformat(),
                    fill_ts.isoformat(),
                    kind,
                ),
            )
            journal.append(c, fill_ts.isoformat(), "fill", json.loads(fill.model_dump_json()))
        return fill

    def mark(self, session: dt.date, closes: dict[str, Decimal], ts: str) -> Decimal:
        acct = self.account()
        pv = sum((q * closes[s] for s, q in acct.positions.items()), Decimal(0))
        eq = acct.cash + pv
        with self.storage.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO equity(session, equity, cash, position_value) VALUES (?,?,?,?)",
                (
                    session.isoformat(),
                    str(eq.quantize(Decimal("0.0001"))),
                    str(acct.cash),
                    str(pv.quantize(Decimal("0.0001"))),
                ),
            )
            journal.append(
                c,
                ts,
                "mark",
                {
                    "session": session,
                    "equity": eq.quantize(Decimal("0.01")),
                    "cash": acct.cash.quantize(Decimal("0.01")),
                },
            )
        return eq
