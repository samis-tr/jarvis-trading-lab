"""Cross-process single-writer lock. The OS releases it automatically if the process dies."""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

from jtl.errors import StorageLocked

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover
    import fcntl


class WriterLock:
    def __init__(self, path: Path):
        self.path = path
        self._fh: BinaryIO | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")  # noqa: SIM115 - held for the life of the Storage object
        try:
            if os.name == "nt":
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:  # pragma: no cover
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            fh.close()
            raise StorageLocked(f"another writer holds {self.path}") from e
        self._fh = fh

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if os.name == "nt":
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None
