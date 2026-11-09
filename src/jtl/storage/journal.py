"""Immutable, hash-chained event journal (append-only; UPDATE/DELETE blocked by SQL triggers)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal
from typing import Any

from jtl.errors import JournalCorrupt
from jtl.safety.secrets import assert_no_secrets

GENESIS = "0" * 64


def _default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return str(o)
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    if hasattr(o, "isoformat"):
        return o.isoformat()
    raise TypeError(f"not serialisable: {type(o)}")


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_default, ensure_ascii=True)


def event_hash(prev_hash: str, seq: int, ts: str, kind: str, payload: str) -> str:
    h = hashlib.sha256()
    for part in (prev_hash, str(seq), ts, kind, payload):
        h.update(part.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def append(conn: sqlite3.Connection, ts: str, kind: str, payload: dict[str, Any]) -> str:
    """Append inside the caller's transaction. Returns the new head hash."""
    body = json.loads(canonical(payload))
    assert_no_secrets(body)
    text = canonical(body)
    row = conn.execute("SELECT seq, hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
    prev_seq, prev_hash = (row[0], row[1]) if row else (0, GENESIS)
    seq = prev_seq + 1
    h = event_hash(prev_hash, seq, ts, kind, text)
    conn.execute(
        "INSERT INTO events(seq, ts, kind, payload, prev_hash, hash) VALUES (?,?,?,?,?,?)",
        (seq, ts, kind, text, prev_hash, h),
    )
    return h


def verify(conn: sqlite3.Connection, after: tuple[int, str] = (0, GENESIS)) -> tuple[int, str]:
    """Recompute the chain (optionally only after a previously verified (seq, hash) checkpoint).

    Raises JournalCorrupt on any gap, edit, reorder or truncation."""
    start_seq, prev = after
    if start_seq:
        row = conn.execute("SELECT hash FROM events WHERE seq = ?", (start_seq,)).fetchone()
        if not row or row[0] != prev:
            raise JournalCorrupt(f"checkpoint seq {start_seq} changed or missing")
    expected_seq = start_seq + 1
    for seq, ts, kind, payload, prev_hash, h in conn.execute(
        "SELECT seq, ts, kind, payload, prev_hash, hash FROM events WHERE seq > ? ORDER BY seq", (start_seq,)
    ):
        if seq != expected_seq:
            raise JournalCorrupt(f"sequence gap at {seq} (expected {expected_seq})")
        if prev_hash != prev:
            raise JournalCorrupt(f"broken link at seq {seq}")
        if event_hash(prev_hash, seq, ts, kind, payload) != h:
            raise JournalCorrupt(f"hash mismatch at seq {seq}")
        prev = h
        expected_seq += 1
    return expected_seq - 1, prev
