"""Alpaca historical DAILY bars connector (data.alpaca.markets only, read-only, guarded).

Requires the user's own Alpaca paper/data keys in env vars. Not used by tests (mocked transport).
"""

from __future__ import annotations

import datetime as dt

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from jtl.errors import DataError
from jtl.market_data.calendar import session_from_timestamp
from jtl.market_data.models import Adjustment, Bar, BarSeries, Provenance, Source
from jtl.safety.endpoints import MARKET_DATA_URL, Purpose
from jtl.safety.http import GuardedClient
from jtl.safety.secrets import read_secret

BARS_URL = f"{MARKET_DATA_URL}/v2/stocks/bars"
MAX_PAGES = 50


class _RawBar(BaseModel):
    model_config = ConfigDict(extra="ignore")
    t: dt.datetime
    o: float
    h: float
    l: float  # noqa: E741 - Alpaca field name
    c: float
    v: float


class _RawPage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    bars: dict[str, list[_RawBar]] | None = None
    next_page_token: str | None = None


class AlpacaDailyBars:
    def __init__(
        self,
        *,
        feed: str = "sip",
        transport: httpx.BaseTransport | None = None,
        key_id: str | None = None,
        secret: str | None = None,
    ):
        key_id = key_id or read_secret("APCA_API_KEY_ID")
        secret = secret or read_secret("APCA_API_SECRET_KEY")
        if not key_id or not secret:
            raise DataError("Alpaca data keys not set (APCA_API_KEY_ID / APCA_API_SECRET_KEY env vars)")
        self.feed = feed
        self._client = GuardedClient(
            Purpose.DATA,
            headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret},
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def fetch(self, symbol: str, start: dt.date, end: dt.date | dt.datetime, adjustment: Adjustment) -> BarSeries:
        params: dict[str, str] = {
            "symbols": symbol,
            "timeframe": "1Day",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "adjustment": adjustment.value,
            "feed": self.feed,
            "limit": "10000",
            "sort": "asc",
        }
        out: list[Bar] = []
        for _ in range(MAX_PAGES):
            try:
                resp = self._client.get(BARS_URL, params=params)
            except httpx.HTTPError as e:
                raise DataError(f"market data request failed: {type(e).__name__}") from e
            if resp.status_code != 200:
                raise DataError(f"market data HTTP {resp.status_code}")
            try:
                page = _RawPage.model_validate(resp.json())
            except (ValueError, ValidationError) as e:
                raise DataError("market data response failed schema validation") from e
            for rb in (page.bars or {}).get(symbol, []):
                try:
                    out.append(
                        Bar(
                            session=session_from_timestamp(rb.t),
                            open=rb.o,
                            high=rb.h,
                            low=rb.l,
                            close=rb.c,
                            volume=rb.v,
                        )
                    )
                except ValidationError as e:
                    raise DataError(f"invalid bar at {rb.t}") from e
            if not page.next_page_token:
                break
            params["page_token"] = page.next_page_token
        else:
            raise DataError("too many pages (refusing)")
        return BarSeries(
            symbol=symbol,
            bars=tuple(out),
            provenance=Provenance(source=Source.ALPACA, adjustment=adjustment, feed=self.feed),
        )
