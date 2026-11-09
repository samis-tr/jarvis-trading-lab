"""Supervisor: runs one session cycle and enforces fail-safes.

Cycle for session t (all times America/New_York):
  OPEN   fill orders decided at t-1's close at t's open (+latency, costs); run protective stops.
  CLOSE  mark to market -> reconcile -> update breakers -> verify journal.
  DECIDE (only on the confirmed close of t) strategy signal -> sizing -> risk engine -> broker (PENDING).

Any SafetyError (bad data, mismatch, unexpected buying power, journal corruption...) trips the latched
`system_halt` breaker: no new orders until a human investigates and resets it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass, field
from decimal import Decimal

from jtl.config import AppConfig
from jtl.domain import OrderIntent, Side, d
from jtl.errors import JournalCorrupt, OrderRejected, SafetyError
from jtl.market_data import calendar
from jtl.market_data.models import BarSeries
from jtl.reconciliation import reconcile
from jtl.risk.breakers import BreakerBook
from jtl.risk.engine import RiskEngine, Snapshot
from jtl.simulator.broker import LocalSimBroker
from jtl.simulator.costs import CostModel
from jtl.storage.db import Storage
from jtl.strategy.sma_trend import SmaTrend, Target

Q = Decimal("0.0001")
FULL_VERIFY_EVERY = 20  # sessions


@dataclass
class SessionResult:
    session: dt.date
    equity: Decimal | None = None
    fills: int = 0
    submitted: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    blocked: str | None = None


def order_id(strategy: str, symbol: str, session: dt.date, side: Side) -> str:
    """Deterministic idempotency key: same decision => same ID, so retries never duplicate."""
    h = hashlib.sha256(f"{strategy}|{symbol}|{session.isoformat()}|{side.value}".encode()).hexdigest()[:12]
    return f"{strategy}-{symbol}-{session:%Y%m%d}-{side.value}-{h}"


class Supervisor:
    def __init__(
        self, cfg: AppConfig, storage: Storage, broker: LocalSimBroker | None = None, strategy: SmaTrend | None = None
    ):
        self.cfg = cfg
        self.storage = storage
        self.broker = broker or LocalSimBroker(storage, CostModel(cfg.simulator), cfg.risk.stop_loss_pct)
        self.strategy = strategy or SmaTrend(cfg.strategy.symbol, cfg.strategy.fast_window, cfg.strategy.slow_window)
        self.breakers = BreakerBook(storage)
        cost_bps = cfg.simulator.half_spread_bps + cfg.simulator.slippage_bps + cfg.simulator.latency_drift_bps
        self.risk = RiskEngine(
            cfg.risk, cfg.symbols, entry_buffer_pct=cfg.simulator.entry_price_buffer_pct, est_cost_bps=cost_bps + 5
        )
        self.starting_cash = d(cfg.simulator.starting_cash)
        self._checkpoint = storage.verify_journal()
        self._sessions_since_full = 0
        self.delay = dt.timedelta(minutes=cfg.data.bar_confirmation_delay_minutes)

    # -- helpers ---------------------------------------------------------------------------------
    def _open_ts(self, s: dt.date) -> dt.datetime:
        return calendar.session_open(s)

    def _close_ts(self, s: dt.date) -> str:
        return (calendar.session_close(s) + self.delay).isoformat()

    def start(self, first_session: dt.date) -> None:
        self.broker.open_account(self.starting_cash, self._open_ts(first_session).isoformat())

    def halt(self, reason: str, session: dt.date) -> None:
        self.breakers.trip("system_halt", reason[:300], session, None, self._close_ts(session))

    @property
    def halted(self) -> bool:
        return any(b.name == "system_halt" for b in self.breakers.all())

    def last_processed(self) -> dt.date | None:
        v = self.storage.kv_get("last_session")
        return dt.date.fromisoformat(v) if v else None

    # -- the cycle -------------------------------------------------------------------------------
    def process_session(
        self, s: dt.date, view: BarSeries, *, bad_sessions: frozenset[dt.date] = frozenset()
    ) -> SessionResult:
        res = SessionResult(s)
        sym = self.strategy.symbol
        try:
            self._verify_journal()
            last = self.last_processed()
            if last is not None and s <= last:
                raise SafetyError(f"session {s} already processed (last {last}) - replay refused")
            if not view.bars or view.bars[-1].session != s:
                raise SafetyError(f"missing bar for {sym} on {s}")
            if any(b.session > s for b in view.bars):
                raise SafetyError("future bar in view (look-ahead) refused")
            if s in bad_sessions:
                raise SafetyError(f"data validation failed for {s} (missing/anomalous/invalid bar)")
            bar = view.bars[-1]

            # OPEN
            open_ts = self._open_ts(s)
            fills = self.broker.fill_pending(s, {sym: bar}, open_ts)
            fills += self.broker.check_stops(s, {sym: bar}, open_ts)
            res.fills = len(fills)
            if any(f.kind.startswith("stop") for f in fills):
                self._set_rearm(sym, True)

            # CLOSE
            ts = self._close_ts(s)
            close_px = d(bar.close)
            equity = self.broker.mark(s, {sym: close_px}, ts)
            res.equity = equity
            acct = self.broker.account()
            reconcile(
                self.storage,
                starting_cash=self.starting_cash,
                reported_cash=acct.cash,
                reported_buying_power=acct.buying_power,
                reported_positions=acct.positions,
            )
            self._update_breakers(s, equity)
            self._set_last(s)
        except SafetyError as e:
            self.halt(f"{type(e).__name__}: {e}", s)
            res.blocked = str(e)
            if isinstance(e, JournalCorrupt):
                raise
            return res

        # DECIDE
        if self.halted:
            res.blocked = "system_halt active - no new orders"
            self.storage.record(ts, "orders_blocked", {"session": s, "reason": res.blocked})
            return res
        self._decide(s, view, close_px, res, ts)
        return res

    def _decide(self, s: dt.date, view: BarSeries, close_px: Decimal, res: SessionResult, ts: str) -> None:
        sym = self.strategy.symbol
        sig = self.strategy.signal(view, s)
        if sig is None:
            return
        self.storage.record(ts, "signal", sig.model_dump(mode="json"))
        acct = self.broker.account()
        held = acct.positions.get(sym, Decimal(0))
        if sig.target is Target.FLAT:
            self._set_rearm(sym, False)
        intent: OrderIntent | None = None
        if sig.target is Target.LONG and held == 0 and not self._rearm_required(sym):
            snap = self._snapshot(s, close_px)
            qty = self.risk.max_buy_qty(snap, sym)
            if qty <= 0:
                res.rejected.append("sized to zero by risk limits")
                self.storage.record(ts, "order_rejected", {"session": s, "reasons": ["sized to zero"]})
                return
            intent = OrderIntent(
                client_order_id=order_id("sma", sym, s, Side.BUY),
                symbol=sym,
                side=Side.BUY,
                qty=qty,
                created_session=s,
                reason="sma trend entry",
            )
        elif sig.target is Target.FLAT and held > 0:
            intent = OrderIntent(
                client_order_id=order_id("sma", sym, s, Side.SELL),
                symbol=sym,
                side=Side.SELL,
                qty=held,
                created_session=s,
                reason="sma trend exit",
            )
        if intent is not None:
            self.submit(intent, close_px, ts, res)

    def submit(self, intent: OrderIntent, ref_price: Decimal, ts: str, res: SessionResult | None = None) -> bool:
        """The ONLY path to the broker: typed intent -> deterministic risk engine -> broker."""
        res = res or SessionResult(intent.created_session)
        if self.halted:
            res.rejected.append("system_halt active")
            self.storage.record(
                ts, "order_rejected", {"intent": intent.model_dump(mode="json"), "reasons": ["system_halt active"]}
            )
            return False
        snap = self._snapshot(intent.created_session, ref_price, symbol=intent.symbol)
        decision = self.risk.evaluate(intent, snap)
        if not decision.approved:
            res.rejected.extend(decision.reasons)
            self.storage.record(
                ts, "order_rejected", {"intent": intent.model_dump(mode="json"), "reasons": decision.reasons}
            )
            return False
        try:
            self._verify_journal(full=True)  # never place an order on top of a corrupt audit trail
        except JournalCorrupt as e:
            self.halt(f"JournalCorrupt: {e}", intent.created_session)
            res.rejected.append("journal corrupt")
            raise
        try:
            self.broker.submit(intent, ts)
        except OrderRejected as e:
            res.rejected.append(e.reason)
            self.storage.record(ts, "order_rejected", {"intent": intent.model_dump(mode="json"), "reasons": [e.reason]})
            return False
        res.submitted.append(intent.client_order_id)
        return True

    # -- state -----------------------------------------------------------------------------------
    def _snapshot(self, s: dt.date, ref_price: Decimal, symbol: str | None = None) -> Snapshot:
        acct = self.broker.account()
        sym = symbol or self.strategy.symbol
        prices = {sym: ref_price}
        pv = sum((q * prices.get(k, Decimal(0)) for k, q in acct.positions.items()), Decimal(0))
        return Snapshot(
            session=s,
            cash=acct.cash,
            buying_power=acct.buying_power,
            equity=acct.cash + pv,
            positions=acct.positions,
            prices=prices,
            pending=self.broker.pending(),
            known_order_ids=self.broker.order_ids(),
            orders_today=self.broker.orders_on(s),
            active_breakers=tuple(self.breakers.active(s)),
        )

    def _update_breakers(self, s: dt.date, equity: Decimal) -> None:
        L = self.cfg.risk
        ts = self._close_ts(s)
        prev = self.storage.query(
            "SELECT equity FROM equity WHERE session < ? ORDER BY session DESC LIMIT 1", (s.isoformat(),)
        )
        if prev:
            pe = Decimal(prev[0][0])
            if pe > 0 and equity / pe - 1 <= -d(L.daily_loss_pause_pct):
                self.breakers.trip("daily_loss", f"daily loss {equity / pe - 1:.2%}", s, calendar.next_session(s), ts)
        monday = s - dt.timedelta(days=s.weekday())
        wk = self.storage.query(
            "SELECT equity FROM equity WHERE session < ? ORDER BY session DESC LIMIT 1", (monday.isoformat(),)
        )
        if wk:
            we = Decimal(wk[0][0])
            if we > 0 and equity / we - 1 <= -d(L.weekly_loss_pause_pct):
                self.breakers.trip(
                    "weekly_loss", f"weekly loss {equity / we - 1:.2%}", s, monday + dt.timedelta(days=6), ts
                )
        peak = Decimal(self.storage.kv_get("peak_equity") or "0")
        if equity > peak:
            with self.storage.tx() as c:
                self.storage.kv_set(c, "peak_equity", str(equity.quantize(Q)))
            peak = equity
        if peak > 0 and equity / peak - 1 <= -d(L.max_drawdown_pct):
            self.breakers.trip("drawdown", f"drawdown {equity / peak - 1:.2%} from peak {peak:.2f}", s, None, ts)

    def _verify_journal(self, full: bool = False) -> None:
        """Incremental check every session; FULL re-hash every N sessions and before every order."""
        self._sessions_since_full += 1
        if full or self._sessions_since_full >= FULL_VERIFY_EVERY:
            self._checkpoint = self.storage.verify_journal()
            self._sessions_since_full = 0
        else:
            self._checkpoint = self.storage.verify_journal(after=self._checkpoint)

    def _set_last(self, s: dt.date) -> None:
        with self.storage.tx() as c:
            self.storage.kv_set(c, "last_session", s.isoformat())

    def _rearm_required(self, sym: str) -> bool:
        return self.storage.kv_get(f"rearm:{sym}") == "1"

    def _set_rearm(self, sym: str, value: bool) -> None:
        with self.storage.tx() as c:
            self.storage.kv_set(c, f"rearm:{sym}", "1" if value else "0")
