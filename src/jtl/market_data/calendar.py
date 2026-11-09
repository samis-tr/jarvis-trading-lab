"""NYSE trading calendar in America/New_York (holidays and early closes via exchange_calendars)."""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from jtl.errors import DataError

NY = ZoneInfo("America/New_York")
_START = "2000-01-03"


@lru_cache(maxsize=1)
def _cal() -> xcals.ExchangeCalendar:
    end = (pd.Timestamp.today() + pd.Timedelta(days=365)).strftime("%Y-%m-%d")
    return xcals.get_calendar("XNYS", start=_START, end=end)


def _ts(d: dt.date) -> pd.Timestamp:
    return pd.Timestamp(d.isoformat())


def is_session(d: dt.date) -> bool:
    try:
        return bool(_cal().is_session(_ts(d)))
    except Exception:
        return False


def sessions_in_range(start: dt.date, end: dt.date) -> list[dt.date]:
    if end < start:
        return []
    return [s.date() for s in _cal().sessions_in_range(_ts(start), _ts(end))]


def next_session(d: dt.date) -> dt.date:
    cal = _cal()
    if cal.is_session(_ts(d)):
        return cal.next_session(_ts(d)).date()
    return cal.date_to_session(_ts(d), direction="next").date()


def previous_session(d: dt.date) -> dt.date:
    cal = _cal()
    if cal.is_session(_ts(d)):
        return cal.previous_session(_ts(d)).date()
    return cal.date_to_session(_ts(d), direction="previous").date()


def session_open(d: dt.date) -> dt.datetime:
    return _cal().session_open(_ts(d)).tz_convert(NY).to_pydatetime()


def session_close(d: dt.date) -> dt.datetime:
    """Close time in New York (16:00, or 13:00 on early-close days)."""
    return _cal().session_close(_ts(d)).tz_convert(NY).to_pydatetime()


def require_aware(now: dt.datetime) -> dt.datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise DataError("naive datetime refused (timezone error)")
    return now.astimezone(NY)


def latest_confirmed_session(now: dt.datetime, delay_minutes: int) -> dt.date:
    """Most recent session whose daily bar is final: close + delay <= now."""
    now_ny = require_aware(now)
    d = now_ny.date()
    candidate = d if is_session(d) else previous_session(d)
    while session_close(candidate) + dt.timedelta(minutes=delay_minutes) > now_ny:
        candidate = previous_session(candidate)
    return candidate


def session_from_timestamp(ts: dt.datetime) -> dt.date:
    """Alpaca daily bars are stamped at 00:00 America/New_York of the session date."""
    ny = require_aware(ts)
    if (ny.hour, ny.minute, ny.second, ny.microsecond) != (0, 0, 0, 0):
        raise DataError(f"daily bar timestamp {ts.isoformat()} is not NY midnight (timezone error)")
    return ny.date()
