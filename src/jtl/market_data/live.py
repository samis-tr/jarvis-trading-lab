"""Live SPY price for DISPLAY ONLY (dashboard). Never used for trading decisions or fills.

Uses Alpaca's free real-time IEX feed (`/v2/stocks/{symbol}/trades/latest`). Results are cached so the
dashboard cannot hammer the API, and any failure simply means "no live price".
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from jtl.market_data import calendar
from jtl.market_data.alpaca import AlpacaDailyBars
from jtl.safety.endpoints import MARKET_DATA_URL

CACHE_SECONDS = 20


@dataclass(frozen=True)
class LiveQuote:
    symbol: str
    price: float
    time: dt.datetime
    source: str = "IEX real-time (display only)"


class _Trade(BaseModel):
    model_config = ConfigDict(extra="ignore")
    t: dt.datetime
    p: float


class _Latest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    trade: _Trade


def market_open_now(now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now(dt.UTC)
    today = now.astimezone(calendar.NY).date()
    if not calendar.is_session(today):
        return False
    return calendar.session_open(today) <= now <= calendar.session_close(today)


class LivePrice:
    def __init__(self, symbol: str, transport: httpx.BaseTransport | None = None):
        self.symbol = symbol
        self._transport = transport
        self._lock = threading.Lock()
        self._cached: tuple[float, LiveQuote | None, str] = (0.0, None, "")

    def get(self) -> tuple[LiveQuote | None, str]:
        """Returns (quote, error). Never raises."""
        with self._lock:
            at, quote, err = self._cached
            if time.monotonic() - at < CACHE_SECONDS:
                return quote, err
            quote, err = self._fetch()
            self._cached = (time.monotonic(), quote, err)
            return quote, err

    def _fetch(self) -> tuple[LiveQuote | None, str]:
        try:
            client = AlpacaDailyBars(feed="iex", transport=self._transport)
        except Exception:
            return None, "no keys"
        try:
            url = f"{MARKET_DATA_URL}/v2/stocks/{self.symbol}/trades/latest"
            resp = client._client.get(url, params={"feed": "iex"})
            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code}"
            tr = _Latest.model_validate(resp.json()).trade
            if not (tr.p > 0) or tr.t.tzinfo is None:
                return None, "bad quote"
            return LiveQuote(self.symbol, tr.p, tr.t), ""
        except (httpx.HTTPError, ValidationError, ValueError) as e:
            return None, type(e).__name__
        except Exception as e:  # display-only: never let this crash the dashboard
            return None, type(e).__name__
        finally:
            client.close()
