"""Deterministic replay: feed historical sessions one by one through the Supervisor.

Same inputs + same config => byte-identical journal (same head hash). Timestamps come from the
NYSE calendar, never from the wall clock.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from jtl.config import AppConfig
from jtl.market_data import calendar
from jtl.market_data.models import BarSeries
from jtl.market_data.validation import ValidationReport, validate_series
from jtl.storage.db import Storage
from jtl.supervisor.supervisor import SessionResult, Supervisor


@dataclass
class ReplayResult:
    db_path: Path
    sessions: int
    journal_events: int
    journal_head: str
    final_equity: Decimal
    halted: bool
    validation: ValidationReport
    results: list[SessionResult]
    hypothetical: bool = True


def run_replay(
    cfg: AppConfig, series: BarSeries, db_path: str | Path, *, start: dt.date | None = None, end: dt.date | None = None
) -> ReplayResult:
    db_path = Path(db_path)
    if db_path.exists():
        raise FileExistsError(f"{db_path} exists - replays always start from a fresh ledger")
    report = validate_series(series, allowlist=cfg.symbols, max_abs_daily_return=cfg.data.max_abs_daily_return)
    bad = frozenset(i.session for i in report.issues)
    first, last = series.bars[0].session, series.bars[-1].session
    start = max(start or first, first)
    end = min(end or last, last)
    by_session = {b.session: i for i, b in enumerate(series.bars)}
    results: list[SessionResult] = []
    with Storage(db_path) as st:
        sup = Supervisor(cfg, st)
        st.record(
            calendar.session_open(start).isoformat(),
            "run_started",
            {
                "mode": cfg.mode.value,
                "symbol": series.symbol,
                "data_label": series.provenance.label,
                "data_source": series.provenance.source.value,
                "adjustment": series.provenance.adjustment.value,
                "start": start,
                "end": end,
                "config": cfg.model_dump(mode="json"),
                "hypothetical": True,
                "validation_issues": len(report.issues),
            },
        )
        sup.start(start)
        for s in calendar.sessions_in_range(start, end):
            idx = by_session.get(s)
            if idx is None:
                # Missing bar: give the supervisor a view whose last bar is stale -> it halts.
                prior = [b for b in series.bars if b.session < s]
                view = BarSeries(symbol=series.symbol, provenance=series.provenance, bars=tuple(prior))
            else:
                view = BarSeries(symbol=series.symbol, provenance=series.provenance, bars=series.bars[: idx + 1])
            results.append(sup.process_session(s, view, bad_sessions=bad))
        count, head = st.verify_journal()
        eq = st.query("SELECT equity FROM equity ORDER BY session DESC LIMIT 1")
        final = Decimal(eq[0][0]) if eq else sup.starting_cash
        halted = sup.halted
    return ReplayResult(
        db_path=db_path,
        sessions=len(results),
        journal_events=count,
        journal_head=head,
        final_equity=final,
        halted=halted,
        validation=report,
        results=results,
    )
