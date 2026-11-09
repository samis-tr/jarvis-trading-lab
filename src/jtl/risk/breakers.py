"""Persistent circuit breakers. Stored in SQLite, so they survive restarts.

* daily_loss  - pause, expires automatically after the next session
* weekly_loss - pause, expires automatically at the end of the ISO week
* drawdown    - LATCHED: never auto-resets; only a human can reset it with an explicit phrase
* system_halt - LATCHED: set by the supervisor on any fail-safe condition
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from jtl.errors import SafetyError
from jtl.storage import journal
from jtl.storage.db import Storage

LATCHED = frozenset({"drawdown", "system_halt"})
RESET_PHRASE = "I UNDERSTAND THIS RESETS A LATCHED SAFETY BREAKER"


@dataclass(frozen=True)
class Breaker:
    name: str
    latched: bool
    reason: str
    tripped_session: dt.date
    until_session: dt.date | None

    def active_on(self, session: dt.date) -> bool:
        return self.latched or (self.until_session is not None and session <= self.until_session)


class BreakerBook:
    def __init__(self, storage: Storage):
        self.storage = storage

    def all(self) -> list[Breaker]:
        rows = self.storage.query("SELECT name, latched, reason, tripped_session, until_session FROM breakers")
        return [
            Breaker(n, bool(lat), r, dt.date.fromisoformat(t), dt.date.fromisoformat(u) if u else None)
            for n, lat, r, t, u in rows
        ]

    def active(self, session: dt.date) -> list[Breaker]:
        return [b for b in self.all() if b.active_on(session)]

    def is_latched(self) -> bool:
        return any(b.latched for b in self.all())

    def trip(self, name: str, reason: str, session: dt.date, until: dt.date | None, ts: str) -> None:
        latched = name in LATCHED
        if latched:
            until = None
        with self.storage.tx() as c:
            row = c.execute("SELECT latched FROM breakers WHERE name = ?", (name,)).fetchone()
            if row and row[0]:
                return  # already latched: keep the original trip record
            c.execute(
                "INSERT INTO breakers(name, latched, reason, tripped_session, until_session) VALUES (?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET latched=excluded.latched, reason=excluded.reason, "
                "tripped_session=excluded.tripped_session, until_session=excluded.until_session",
                (name, int(latched), reason, session.isoformat(), until.isoformat() if until else None),
            )
            journal.append(
                c,
                ts,
                "breaker_tripped",
                {"name": name, "latched": latched, "reason": reason, "session": session, "until": until},
            )

    def manual_reset(self, name: str, confirm: str, operator: str, ts: str) -> None:
        """Human-only reset. Not exposed to the dashboard, the strategy, or any LLM interface."""
        if confirm != RESET_PHRASE:
            raise SafetyError("reset refused: confirmation phrase mismatch")
        if not operator or not operator.strip():
            raise SafetyError("reset refused: operator name required")
        with self.storage.tx() as c:
            if not c.execute("SELECT 1 FROM breakers WHERE name = ?", (name,)).fetchone():
                raise SafetyError(f"no breaker named {name}")
            c.execute("DELETE FROM breakers WHERE name = ?", (name,))
            if name == "drawdown":
                c.execute("DELETE FROM kv WHERE key = 'peak_equity'")
            journal.append(c, ts, "breaker_manual_reset", {"name": name, "operator": operator.strip()[:40]})
