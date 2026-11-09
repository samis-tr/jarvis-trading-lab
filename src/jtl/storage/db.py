"""Storage facade: one writer per DB file, WAL, migrations, transactions, backups."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from jtl.errors import JournalCorrupt
from jtl.storage import journal
from jtl.storage.lock import WriterLock
from jtl.storage.migrations import MIGRATIONS


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = WriterLock(self.path.with_suffix(self.path.suffix + ".lock"))
        self._lock.acquire()
        self._mutex = threading.RLock()
        try:
            self.conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA busy_timeout=5000")
            self._migrate()
            self.verify_journal()
        except Exception:
            with contextlib.suppress(Exception):
                self.conn.close()
            self._lock.release()
            raise

    # -- lifecycle ---------------------------------------------------------------------------
    def close(self) -> None:
        with self._mutex:
            with contextlib.suppress(Exception):
                self.conn.close()
            self._lock.release()

    def __enter__(self) -> Storage:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _migrate(self) -> None:
        c = self.conn
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT)")
        applied = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
        for version, statements in MIGRATIONS:
            if version in applied:
                continue
            c.execute("BEGIN IMMEDIATE")
            try:
                for stmt in statements:
                    c.execute(stmt)
                c.execute("INSERT INTO schema_migrations VALUES (?, ?)", (version, dt.datetime.now(dt.UTC).isoformat()))
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise

    @property
    def schema_version(self) -> int:
        return self.query("SELECT COALESCE(MAX(version),0) FROM schema_migrations")[0][0]

    # -- transactions ------------------------------------------------------------------------
    @contextlib.contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._mutex:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            self.conn.execute("COMMIT")

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        with self._mutex:
            return self.conn.execute(sql, params).fetchall()

    # -- journal -----------------------------------------------------------------------------
    def record(self, ts: str, kind: str, payload: dict[str, Any]) -> str:
        with self.tx() as c:
            return journal.append(c, ts, kind, payload)

    def verify_journal(self, after: tuple[int, str] | None = None) -> tuple[int, str]:
        with self._mutex:
            try:
                return journal.verify(self.conn, after) if after else journal.verify(self.conn)
            except sqlite3.DatabaseError as e:
                raise JournalCorrupt(f"journal unreadable: {e}") from e

    def events(self, limit: int = 100, kind: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT seq, ts, kind, payload, hash FROM events"
        params: tuple[Any, ...] = ()
        if kind:
            sql += " WHERE kind = ?"
            params = (kind,)
        sql += " ORDER BY seq DESC LIMIT ?"
        params += (limit,)
        return [dict(seq=s, ts=t, kind=k, payload=json.loads(p), hash=h) for s, t, k, p, h in self.query(sql, params)]

    # -- kv ----------------------------------------------------------------------------------
    def kv_get(self, key: str, default: str | None = None) -> str | None:
        r = self.query("SELECT value FROM kv WHERE key = ?", (key,))
        return r[0][0] if r else default

    @staticmethod
    def kv_set(conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    # -- backup ------------------------------------------------------------------------------
    def backup(self, backup_dir: str | Path, label: str | None = None) -> Path:
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = label or dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        dest = backup_dir / f"{self.path.stem}-{stamp}.db"
        with self._mutex:
            self.verify_journal()
            target = sqlite3.connect(dest)
            try:
                self.conn.backup(target)
            finally:
                target.close()
        return dest
