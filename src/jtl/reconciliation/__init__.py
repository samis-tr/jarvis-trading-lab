"""Reconciliation: independently rebuild cash/positions from the fill history and compare with
what the broker reports. Any mismatch (or buying power above cash) is a fail-safe halt."""

from __future__ import annotations

from decimal import Decimal

from jtl.errors import ReconciliationMismatch
from jtl.storage.db import Storage

TOL = Decimal("0.01")


def expected_from_fills(storage: Storage, starting_cash: Decimal) -> tuple[Decimal, dict[str, Decimal]]:
    cash = starting_cash
    pos: dict[str, Decimal] = {}
    for sym, side, qty, price, fees in storage.query("SELECT symbol, side, qty, price, fees FROM fills ORDER BY rowid"):
        q, p, f = Decimal(qty), Decimal(price), Decimal(fees)
        if side == "buy":
            cash -= q * p + f
            pos[sym] = pos.get(sym, Decimal(0)) + q
        else:
            cash += q * p - f
            pos[sym] = pos.get(sym, Decimal(0)) - q
    return cash, {s: q for s, q in pos.items() if q != 0}


def reconcile(
    storage: Storage,
    *,
    starting_cash: Decimal,
    reported_cash: Decimal,
    reported_buying_power: Decimal,
    reported_positions: dict[str, Decimal],
) -> None:
    exp_cash, exp_pos = expected_from_fills(storage, starting_cash)
    problems = []
    if abs(exp_cash - reported_cash) > TOL:
        problems.append(f"cash expected {exp_cash:.2f} reported {reported_cash:.2f}")
    if reported_buying_power > reported_cash + TOL:
        problems.append(f"unexpected buying power {reported_buying_power:.2f} > cash {reported_cash:.2f}")
    rep = {s: q for s, q in reported_positions.items() if q != 0}
    if set(rep) != set(exp_pos) or any(abs(rep[s] - exp_pos[s]) > Decimal("0.00001") for s in rep):
        problems.append(f"positions expected {exp_pos} reported {rep}")
    if any(q < 0 for q in rep.values()):
        problems.append("negative position reported")
    if problems:
        raise ReconciliationMismatch("; ".join(problems))
