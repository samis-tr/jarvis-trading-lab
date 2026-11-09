"""Bot comparison: every bot gets its OWN fresh ledger with identical cash, costs, risk limits, data
and trading start date, then they are ranked. All results are HYPOTHETICAL.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

from jtl import HYPOTHETICAL_BANNER
from jtl.analytics import Metrics, buy_and_hold, cash_benchmark, strategy_metrics
from jtl.config import AppConfig
from jtl.market_data.models import BarSeries
from jtl.safety.secrets import assert_no_secrets
from jtl.simulator.engine import run_replay
from jtl.storage.db import Storage
from jtl.strategy.base import Strategy


@dataclass
class BotResult:
    name: str
    title: str
    metrics: Metrics
    halted: bool
    breakers: list[str]
    curve: list[tuple[str, float]]


def _with_cash(cfg: AppConfig, cash: float) -> AppConfig:
    return cfg.model_copy(update={"simulator": cfg.simulator.model_copy(update={"starting_cash": float(cash)})})


def run_comparison(
    cfg: AppConfig,
    series: BarSeries,
    out_dir: str | Path,
    *,
    bots: list[Strategy],
    cash: float,
    total_return: BarSeries | None = None,
    period_label: str = "in-sample",
) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=False)
    cfg = _with_cash(cfg, cash)
    warm = max(b.warmup for b in bots)
    if len(series.bars) <= warm + 20:
        raise ValueError("not enough bars for the slowest bot's warm-up")
    start = series.bars[warm].session  # identical trading start for every bot (warm-up bars are history only)
    for bot in bots:
        run_replay(cfg, series, out / f"{bot.name}.db", start=start, strategy=bot)
    return build_board(
        out,
        bots,
        series,
        cash,
        total_return=total_return,
        period_label=period_label,
        notes=[
            "Every bot: same data, same start date, same cash, same costs, same risk limits.",
            RISK_NOTE,
            "Ranking on past data can be luck. The sealed out-of-sample period was not used here.",
        ],
    )


RISK_NOTE = (
    "Risk limits (0.5% risk per trade, 5% stop, <=20% position) keep bots mostly in cash, so their returns "
    "are much smaller than a 100%-invested benchmark - and so are their drawdowns."
)


def _metrics(st: Storage, title: str, cash: float) -> Metrics:
    rows = st.query("SELECT session, equity FROM equity ORDER BY session")
    if len(rows) >= 2:
        return strategy_metrics(st, label=title)
    s = dt.date.fromisoformat(rows[0][0]) if rows else dt.date.today()
    v = float(rows[0][1]) if rows else cash
    return Metrics(title, s, s, cash, v, v / cash - 1, 0.0, min(0.0, v / cash - 1), None)


def build_board(
    out: Path,
    bots: list[Strategy],
    series: BarSeries,
    cash: float,
    *,
    total_return: BarSeries | None,
    period_label: str,
    notes: list[str],
) -> dict:
    """Read each bot's ledger in `out` and write leaderboard.json / leaderboard.md there."""
    results: list[BotResult] = []
    for bot in bots:
        with Storage(out / f"{bot.name}.db") as st:
            m = _metrics(st, bot.title, cash)
            breakers = [r[0] for r in st.query("SELECT name FROM breakers")]
            halted = "system_halt" in breakers
            curve = [(s, float(e)) for s, e in st.query("SELECT session, equity FROM equity ORDER BY session")]
        step = 5 if len(curve) > 300 else 1
        thin = curve[::step]
        if curve and thin[-1] != curve[-1]:
            thin.append(curve[-1])
        results.append(BotResult(bot.name, bot.title, m, halted, breakers, thin))
    results.sort(key=lambda r: r.metrics.end_value, reverse=True)
    s0, s1 = results[0].metrics.start, results[0].metrics.end
    bench: list[Metrics] = []
    if len([b for b in series.bars if s0 <= b.session <= s1]) >= 2:
        bench.append(buy_and_hold(series, s0, s1, cash, "Benchmark: SPY buy & hold, 100% invested, price-only"))
        if total_return is not None:
            bench.append(
                buy_and_hold(total_return, s0, s1, cash, "Benchmark: SPY buy & hold, 100% invested, total return")
            )
    bench.append(cash_benchmark(s0, s1, cash))
    board = {
        "hypothetical": True,
        "disclaimer": HYPOTHETICAL_BANNER,
        "data_label": series.provenance.label,
        "data_is_real": series.provenance.is_real,
        "period": period_label,
        "start": s0.isoformat(),
        "end": s1.isoformat(),
        "starting_cash": cash,
        "currency": "USD",
        "bots": [
            {
                "rank": i + 1,
                "name": r.name,
                "title": r.title,
                "halted": r.halted,
                "breakers": r.breakers,
                **{k: v for k, v in r.metrics.as_dict().items() if k not in ("label", "notes", "disclaimer")},
                "curve": r.curve,
            }
            for i, r in enumerate(results)
        ],
        "benchmarks": [b.as_dict() for b in bench],
        "notes": notes,
    }
    assert_no_secrets(board)
    (out / "leaderboard.json").write_text(json.dumps(board, indent=2), encoding="utf-8")
    (out / "leaderboard.md").write_text(_markdown(board), encoding="utf-8")
    return board


def _markdown(b: dict) -> str:
    lines = [
        f"# Bot leaderboard ({b['period']}, {b['start']} -> {b['end']})",
        "",
        f"> **{b['disclaimer']}**",
        "",
        f"- Data: {b['data_label']}",
        f"- Starting cash per bot: ${b['starting_cash']:,.2f} (virtual)",
        "",
        "| # | Bot | End value | Return | CAGR | Max DD | Trades | Breakers |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in b["bots"]:
        lines.append(
            f"| {r['rank']} | {r['title']} | ${r['end_value']:,.2f} | {r['total_return']:+.2%} | {r['cagr']:+.2%} | "
            f"{r['max_drawdown']:.2%} | {r['trades']} | {', '.join(r['breakers']) or '-'} |"
        )
    lines += ["", "| Benchmark | End value | Return | Max DD |", "|---|---|---|---|"]
    for m in b["benchmarks"]:
        lines.append(f"| {m['label']} | ${m['end_value']:,.2f} | {m['total_return']:+.2%} | {m['max_drawdown']:.2%} |")
    lines += ["", "## Notes", *[f"- {n}" for n in b["notes"]]]
    return "\n".join(lines) + "\n"
