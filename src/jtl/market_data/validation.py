"""Schema, calendar, anomaly and freshness validation. Any failure => no new orders."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from jtl.errors import DataError, InsufficientData
from jtl.market_data import calendar
from jtl.market_data.models import BarSeries


@dataclass(frozen=True)
class Issue:
    session: dt.date
    kind: str  # duplicate | unordered | not_session | missing | ohlc | anomaly
    detail: str


@dataclass
class ValidationReport:
    symbol: str
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def first_bad_session(self) -> dt.date | None:
        return min((i.session for i in self.issues), default=None)

    def raise_if_bad(self) -> None:
        if self.issues:
            i = self.issues[0]
            raise DataError(
                f"{self.symbol}: {len(self.issues)} data issue(s); first: {i.kind} on {i.session}: {i.detail}"
            )


def validate_series(series: BarSeries, *, allowlist: tuple[str, ...], max_abs_daily_return: float) -> ValidationReport:
    if series.symbol not in allowlist:
        raise DataError(f"symbol {series.symbol!r} not in allowlist")
    rep = ValidationReport(series.symbol)
    bars = series.bars
    if not bars:
        raise DataError("empty series")
    prev = None
    for b in bars:
        if prev is not None:
            if b.session == prev.session:
                rep.issues.append(Issue(b.session, "duplicate", "duplicate session"))
                continue
            if b.session < prev.session:
                rep.issues.append(Issue(b.session, "unordered", "bars not in ascending order"))
                continue
        if not calendar.is_session(b.session):
            rep.issues.append(Issue(b.session, "not_session", "date is not an NYSE session"))
        if not (b.low <= min(b.open, b.close) and b.high >= max(b.open, b.close) and b.low <= b.high):
            rep.issues.append(Issue(b.session, "ohlc", "inconsistent OHLC"))
        if prev is not None:
            r = b.close / prev.close - 1.0
            g = b.open / prev.close - 1.0
            if abs(r) > max_abs_daily_return or abs(g) > max_abs_daily_return:
                rep.issues.append(Issue(b.session, "anomaly", f"move {r:+.2%} / gap {g:+.2%} exceeds limit"))
        prev = b
    expected = calendar.sessions_in_range(bars[0].session, bars[-1].session)
    have = {b.session for b in bars}
    for s in expected:
        if s not in have:
            rep.issues.append(Issue(s, "missing", "missing bar for NYSE session"))
    rep.issues.sort(key=lambda i: (i.session, i.kind))
    return rep


def check_fresh(series: BarSeries, as_of: dt.datetime, delay_minutes: int) -> dt.date:
    """The newest bar must be exactly the latest *confirmed closed* session. Returns that session."""
    expected = calendar.latest_confirmed_session(as_of, delay_minutes)
    if not series.bars:
        raise DataError("no bars")
    last = series.bars[-1].session
    if last > expected:
        raise DataError(f"bar for {last} is not yet confirmed closed (latest confirmed {expected})")
    if last < expected:
        raise DataError(f"stale data: newest bar {last}, expected {expected}")
    return last


def check_sufficient(series: BarSeries, min_years: float) -> None:
    if len(series) < 2:
        raise InsufficientData("fewer than 2 bars")
    span = (series.bars[-1].session - series.bars[0].session).days / 365.25
    if span < min_years:
        raise InsufficientData(f"only {span:.2f} years of history; need >= {min_years}")
