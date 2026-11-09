"""Secrets come ONLY from environment variables and must never reach logs, journal, reports or git."""

from __future__ import annotations

import os
import re
from typing import Any

from jtl.errors import SecretLeak

SECRET_ENV_VARS = ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY")
_SECRET_KEY_RE = re.compile(r"(secret|password|passwd|token|api[_-]?key|key[_-]?id|authorization)", re.I)


def read_secret(name: str) -> str | None:
    if name not in SECRET_ENV_VARS:
        raise SecretLeak(f"{name} is not a recognised secret env var")
    v = os.environ.get(name, "").strip()
    return v or None


def _secret_values() -> list[str]:
    return [v for n in SECRET_ENV_VARS if (v := os.environ.get(n, "").strip()) and len(v) >= 6]


def assert_no_secrets(obj: Any, _path: str = "") -> None:
    """Raise if obj (json-like) contains secret-looking keys or any live secret value."""
    values = _secret_values()

    def walk(o: Any, path: str) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if _SECRET_KEY_RE.search(str(k)):
                    raise SecretLeak(f"secret-like field {path}/{k} refused")
                walk(v, f"{path}/{k}")
        elif isinstance(o, list | tuple):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")
        elif isinstance(o, str):
            for s in values:
                if s in o:
                    raise SecretLeak(f"secret value found at {path or '/'}")

    walk(obj, _path)


def redact(text: str) -> str:
    for s in _secret_values():
        text = text.replace(s, "***REDACTED***")
    return text
