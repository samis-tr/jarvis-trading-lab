"""Daily FORWARD paper simulation: every bot keeps its own persistent virtual account and advances
one confirmed NYSE session at a time as real days pass. No broker and no orders leave this PC.

Each `forward_step`:
  1. drops any bar that is not yet confirmed closed (Alpaca returns an in-progress bar intraday);
  2. requires the newest bar to be the latest confirmed session (stale data -> nothing happens);
  3. checks that history did not silently change (split / data revision -> latched halt);
  4. processes every missed session since the last run (catch-up after the PC was off);
  5. rewrites the forward leaderboard.

Running it twice in a day is harmless: an already-processed session is never processed again.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from jtl.config import AppConfig
from jtl.errors import DataError
from jtl.market_data import calendar
from jtl.market_data.models import BarSeries
from jtl.market_data.validation import check_fresh, validate_series
from jtl.simulator.compare import RISK_NOTE, _with_cash, build_board
from jtl.storage.db import Storage
from jtl.strategy.base import Strategy
from jtl.supervisor.supervisor import Supervisor

REVISION_TOLERANCE = 0.001  # 0.1% change in an already-used close => data revision / corporate action


@dataclass
class BotStep:
    name: str
    started: bool = False
    processed: list[str] = field(default_factory=list)
    submitted: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)


@dataclass
class ForwardResult:
    latest_session: dt.date
    bots: list[BotStep]
    board: dict


def forward_step(
    cfg: AppConfig,
    price: BarSeries,
    root: str | Path,
    *,
    bots: list[Strategy],
    now: dt.datetime,
    total_return: BarSeries | None = None,
) -> ForwardResult:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    cash = cfg.simulator.starting_cash
    cfg = _with_cash(cfg, cash)
    delay = cfg.data.bar_confirmation_delay_minutes
    confirmed = calendar.latest_confirmed_session(now, delay)
    price = price.upto(confirmed)  # never use an unfinished (intraday) bar
    if total_return is not None:
        total_return = total_return.upto(confirmed)
    latest = check_fresh(price, now, delay)  # raises DataError if stale
    report = validate_series(price, allowlist=cfg.symbols, max_abs_daily_return=cfg.data.max_abs_daily_return)
    bad = frozenset(i.session for i in report.issues)
    idx = {b.session: i for i, b in enumerate(price.bars)}
    if len(price.bars) < max(b.warmup for b in bots) + 1:
        raise DataError("not enough history for the slowest bot's warm-up")

    steps: list[BotStep] = []
    for bot in bots:
        step = BotStep(bot.name)
        with Storage(root / f"{bot.name}.db") as st:
            sup = Supervisor(cfg, st, strategy=bot)
            if st.kv_get("forward_start") is None:
                sup.start(latest)
                st.record(
                    calendar.session_open(latest).isoformat(),
                    "forward_started",
                    {
                        "strategy": bot.name,
                        "start_session": latest,
                        "starting_cash": cash,
                        "data_label": price.provenance.label,
                        "hypothetical": True,
                    },
                )
                with st.tx() as c:
                    st.kv_set(c, "forward_start", latest.isoformat())
                step.started = True
                todo = [latest]
            else:
                last = sup.last_processed()
                todo = calendar.sessions_in_range(calendar.next_session(last), latest) if last and last < latest else []
                _check_revision(st, sup, price, last)
            for s in todo:
                i = idx.get(s)
                view = (
                    BarSeries(symbol=price.symbol, provenance=price.provenance, bars=price.bars[: i + 1])
                    if i is not None
                    else BarSeries(
                        symbol=price.symbol,
                        provenance=price.provenance,
                        bars=tuple(b for b in price.bars if b.session < s),
                    )
                )
                res = sup.process_session(s, view, bad_sessions=bad)
                step.processed.append(s.isoformat())
                step.submitted += res.submitted
                if res.blocked:
                    step.blocked.append(f"{s}: {res.blocked}")
                if i is not None:
                    with st.tx() as c:
                        st.kv_set(c, f"close:{s.isoformat()}", repr(price.bars[i].close))
        steps.append(step)

    starts = {_kv(root / f"{b.name}.db", "forward_start") for b in bots}
    board = build_board(
        root,
        bots,
        price,
        cash,
        total_return=total_return,
        period_label=f"FORWARD paper simulation since {min(starts)}",
        notes=[
            "Forward test: each bot only sees days that happened AFTER it started - no hindsight possible.",
            "Every bot: same data, same start date, same cash, same costs, same risk limits.",
            RISK_NOTE,
            "A few weeks or months of forward results say very little; judge only after many trades.",
        ],
    )
    return ForwardResult(latest, steps, board)


def _check_revision(st: Storage, sup: Supervisor, price: BarSeries, last: dt.date | None) -> None:
    """If a close we already traded on has changed, the data was revised (e.g. a split) -> halt."""
    if last is None:
        return
    stored = st.kv_get(f"close:{last.isoformat()}")
    bar = next((b for b in price.bars if b.session == last), None)
    if stored is None or bar is None:
        return
    old = float(stored)
    if abs(bar.close / old - 1) > REVISION_TOLERANCE:
        sup.halt(f"data revision on {last}: close {old} -> {bar.close} (split or correction?)", last)


def _kv(path: Path, key: str) -> str:
    with Storage(path) as st:
        return st.kv_get(key) or ""
