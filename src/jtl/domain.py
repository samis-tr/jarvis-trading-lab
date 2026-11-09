"""Typed domain model. Only long-only, cash, US-equity market/limit DAY orders can be expressed."""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

QTY_STEP = Decimal("0.0001")
CENT = Decimal("0.01")


def d(x: float | int | str | Decimal) -> Decimal:
    """Deterministic Decimal conversion (via str, never binary float repr)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(repr(round(x, 8)))
    return Decimal(str(x))


def qty_floor(q: Decimal) -> Decimal:
    return q.quantize(QTY_STEP, rounding=ROUND_DOWN)


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=False)


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(StrEnum):
    DAY = "day"


class AssetClass(StrEnum):
    US_EQUITY = "us_equity"


class OrderStatus(StrEnum):
    PENDING = "pending"  # accepted by risk, waiting for next session open
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class OrderIntent(Frozen):
    """What a strategy / human wants. Must pass validation + risk before becoming an Order."""

    client_order_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    symbol: str = Field(min_length=1, max_length=10, pattern=r"^[A-Z.]+$")
    side: Side
    qty: Decimal = Field(gt=0)
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    asset_class: AssetClass = AssetClass.US_EQUITY
    created_session: dt.date
    reason: str = Field(default="", max_length=200)
    is_protective_exit: bool = False

    @field_validator("qty")
    @classmethod
    def _qty_step(cls, v: Decimal) -> Decimal:
        if v != qty_floor(v):
            raise ValueError("qty must be a multiple of 0.0001")
        return v


class Order(Frozen):
    intent: OrderIntent
    status: OrderStatus
    stop_price: Decimal | None = None


class Fill(Frozen):
    client_order_id: str
    symbol: str
    side: Side
    qty: Decimal
    price: Decimal
    reference_price: Decimal
    fees: Decimal
    session: dt.date
    timestamp: dt.datetime
    kind: str = "open"  # open | stop | stop_gap


class Position(Frozen):
    symbol: str
    qty: Decimal
    avg_cost: Decimal
    stop_price: Decimal | None = None
