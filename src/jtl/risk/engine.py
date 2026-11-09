"""Deterministic pre-trade risk engine. Pure function of (intent, snapshot, limits, breakers).

Nothing - strategy, dashboard, Jarvis, or an LLM - can submit an order without passing `evaluate`.
Limits are a frozen config object; there is no setter.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from jtl.config import RiskConfig
from jtl.domain import OrderIntent, Side, d, qty_floor
from jtl.risk.breakers import Breaker

EPS = Decimal("0.005")


@dataclass(frozen=True)
class PendingOrder:
    client_order_id: str
    symbol: str
    side: Side
    qty: Decimal


@dataclass(frozen=True)
class Snapshot:
    session: dt.date
    cash: Decimal
    buying_power: Decimal
    equity: Decimal
    positions: dict[str, Decimal]  # symbol -> qty (long only, >= 0)
    prices: dict[str, Decimal]  # symbol -> reference price (last confirmed close)
    pending: tuple[PendingOrder, ...] = ()
    known_order_ids: frozenset[str] = frozenset()
    orders_today: int = 0
    active_breakers: tuple[Breaker, ...] = ()


@dataclass
class Decision:
    approved: bool
    reasons: list[str] = field(default_factory=list)


class RiskEngine:
    def __init__(
        self,
        limits: RiskConfig,
        allowlist: tuple[str, ...],
        *,
        entry_buffer_pct: float = 0.03,
        est_cost_bps: float = 10.0,
    ):
        self.limits = limits
        self.allowlist = allowlist
        self.buffer = d(entry_buffer_pct)
        self.cost = d(est_cost_bps) / Decimal(10_000)

    # -- sizing (advisory; evaluate() re-checks everything independently) -------------------------
    def max_buy_qty(self, snap: Snapshot, symbol: str) -> Decimal:
        px = snap.prices.get(symbol)
        if px is None or px <= 0 or snap.equity <= 0:
            return Decimal(0)
        est_px = px * (1 + self.buffer)
        held = snap.positions.get(symbol, Decimal(0))
        pend_buy = sum((p.qty for p in snap.pending if p.symbol == symbol and p.side is Side.BUY), Decimal(0))
        risk_qty = snap.equity * d(self.limits.max_risk_per_trade_pct) / (px * d(self.limits.stop_loss_pct))
        pos_qty = snap.equity * d(self.limits.max_position_pct) / est_px - held - pend_buy
        cash_qty = (self._free_cash(snap)) / (est_px * (1 + self.cost))
        q = min(risk_qty, pos_qty, cash_qty)
        if q <= 0:
            return Decimal(0)
        q = qty_floor(q)
        return q if self.limits.allow_fractional else Decimal(int(q))

    def _free_cash(self, snap: Snapshot) -> Decimal:
        reserved = Decimal(0)
        for p in snap.pending:
            if p.side is Side.BUY:
                px = snap.prices.get(p.symbol, Decimal(0))
                reserved += p.qty * px * (1 + self.buffer) * (1 + self.cost)
        return snap.cash - reserved

    # -- the gate --------------------------------------------------------------------------------
    def evaluate(self, intent: OrderIntent, snap: Snapshot) -> Decision:
        r: list[str] = []
        L = self.limits
        sym = intent.symbol
        if sym not in self.allowlist:
            r.append(f"symbol {sym} not in allowlist")
        if intent.created_session != snap.session:
            r.append("intent session does not match snapshot session")
        if snap.buying_power > snap.cash + EPS:
            r.append("unexpected buying power above cash (margin?) - refusing")
        if snap.cash < 0:
            r.append("negative cash")
        if any(q < 0 for q in snap.positions.values()):
            r.append("negative position detected")
        if intent.client_order_id in snap.known_order_ids:
            r.append("duplicate client_order_id")
        if any(p.symbol == sym for p in snap.pending):
            r.append(f"concurrent order already pending for {sym}")
        if snap.orders_today >= L.max_orders_per_day:
            r.append("max orders per day reached")
        if not L.allow_fractional and intent.qty != intent.qty.to_integral_value():
            r.append("fractional quantity not allowed")
        px = snap.prices.get(sym)
        if px is None or px <= 0:
            r.append("no reference price")
            return Decision(False, r)

        risk_reducing = intent.side is Side.SELL
        if not risk_reducing:
            for b in snap.active_breakers:
                r.append(f"breaker active: {b.name} ({b.reason})")
        elif intent.qty > snap.positions.get(sym, Decimal(0)):
            r.append("sell exceeds position (shorting is not allowed)")

        if intent.side is Side.BUY:
            est_px = px * (1 + self.buffer)
            est_cost = intent.qty * est_px * (1 + self.cost)
            if est_cost > self._free_cash(snap) + EPS:
                r.append("insufficient cash (cash-only account, pending buys reserved)")
            held = snap.positions.get(sym, Decimal(0))
            pend_buy = sum((p.qty for p in snap.pending if p.symbol == sym and p.side is Side.BUY), Decimal(0))
            exposure = (held + pend_buy + intent.qty) * est_px
            if exposure > snap.equity * d(L.max_position_pct) + EPS:
                r.append(f"combined exposure {exposure:.2f} exceeds {L.max_position_pct:.0%} of equity")
            trade_risk = intent.qty * px * d(L.stop_loss_pct)
            if trade_risk > snap.equity * d(L.max_risk_per_trade_pct) + EPS:
                r.append(f"trade risk {trade_risk:.2f} exceeds {L.max_risk_per_trade_pct:.2%} of equity")
        return Decision(not r, r)
