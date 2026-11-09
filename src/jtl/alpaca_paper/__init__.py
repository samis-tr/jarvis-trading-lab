"""Alpaca PAPER trading adapter - STUB (Phase 4, requires explicit user permission).

In Phase 1-2 this adapter performs NO network calls at all. Every order method raises
PaperTradingNotEnabled before any request is built. The only trading destination it could ever use
is the hardcoded PAPER endpoint; there is no parameter, env var or config key to change it, and
there is no live adapter or live toggle anywhere in this codebase.
"""

from __future__ import annotations

from jtl.domain import OrderIntent
from jtl.errors import PaperTradingNotEnabled
from jtl.safety.endpoints import PAPER_TRADING_URL, Purpose, validate_destination
from jtl.safety.gate import paper_trading_allowed

PHASE4_ENABLED = False  # flipping this requires Phase 4 work + explicit user permission
ORDERS_URL = validate_destination(f"{PAPER_TRADING_URL}/v2/orders", Purpose.TRADING)


class AlpacaPaperBroker:
    name = "alpaca_paper"

    def __init__(self, *_: object, **__: object):
        allowed, reasons = paper_trading_allowed()
        if not (PHASE4_ENABLED and allowed):
            raise PaperTradingNotEnabled("Alpaca paper trading is not enabled: " + "; ".join(reasons))

    def submit(self, intent: OrderIntent, ts: str) -> None:  # pragma: no cover - unreachable in Phase 2
        raise PaperTradingNotEnabled("paper order submission is not implemented before Phase 4")
