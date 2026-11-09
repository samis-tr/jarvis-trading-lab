"""Hardcoded network destinations. There is NO way to configure a broker URL.

Only two hosts may ever be contacted:
  * paper-api.alpaca.markets  (trading - PAPER ONLY, disabled until Phase 4)
  * data.alpaca.markets       (historical market data)
"""

from __future__ import annotations

import os
from enum import StrEnum
from urllib.parse import urlsplit

from jtl.errors import ConfigRejected, DestinationRejected

PAPER_TRADING_URL = "https://paper-api.alpaca.markets"
MARKET_DATA_URL = "https://data.alpaca.markets"

# Known real-money endpoints - explicitly denied (defence in depth; allowlist already excludes them).
LIVE_DENYLIST = frozenset({"api.alpaca.markets", "broker-api.alpaca.markets"})


class Purpose(StrEnum):
    TRADING = "trading"
    DATA = "data"


_ALLOWED: dict[Purpose, tuple[str, tuple[str, ...]]] = {
    Purpose.TRADING: ("paper-api.alpaca.markets", ("/v2/",)),
    Purpose.DATA: ("data.alpaca.markets", ("/v2/stocks/",)),
}

BASE_URL_ENV_VARS = ("APCA_API_BASE_URL", "ALPACA_BASE_URL", "ALPACA_API_BASE_URL", "APCA_BASE_URL")


def validate_destination(url: str, purpose: Purpose) -> str:
    """Return the URL if, and only if, it is exactly an allowed host/path for `purpose`."""
    if not isinstance(url, str) or not url or any(c.isspace() for c in url) or "\\" in url:
        raise DestinationRejected("malformed URL")
    if not url.isascii():
        raise DestinationRejected("non-ASCII URL (possible homograph)")
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise DestinationRejected(f"scheme {parts.scheme!r} not allowed (https only)")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise DestinationRejected("userinfo in URL not allowed")
    host = (parts.hostname or "").lower()
    if host in LIVE_DENYLIST:
        raise DestinationRejected(f"LIVE trading host {host!r} is permanently forbidden")
    try:
        port = parts.port
    except ValueError as e:
        raise DestinationRejected("bad port") from e
    if port not in (None, 443):
        raise DestinationRejected("non-default port not allowed")
    allowed_host, prefixes = _ALLOWED[purpose]
    if host != allowed_host or parts.netloc.lower() not in (allowed_host, f"{allowed_host}:443"):
        raise DestinationRejected(f"host {host!r} not allowed for {purpose}")
    if not any(parts.path.startswith(p) for p in prefixes):
        raise DestinationRejected(f"path {parts.path!r} not allowed for {purpose}")
    if parts.fragment:
        raise DestinationRejected("fragment not allowed")
    return url


def check_environment(environ: dict[str, str] | None = None) -> None:
    """Fail closed if the environment tries to redirect the broker anywhere.

    Setting a base-URL variable to the paper URL is tolerated (and ignored - we always use the
    hardcoded constant). Anything else is treated as suspicious configuration.
    """
    env = os.environ if environ is None else environ
    for name in BASE_URL_ENV_VARS:
        val = env.get(name)
        if val is None or val.strip() == "":
            continue
        if val.strip().rstrip("/").lower() != PAPER_TRADING_URL:
            raise ConfigRejected(f"environment variable {name} points to a non-paper destination; refusing")
