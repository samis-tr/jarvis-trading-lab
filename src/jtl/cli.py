"""Command line interface. `python -m jtl <command>` (or `jtl <command>` after setup)."""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
import tempfile
from pathlib import Path

from jtl import HYPOTHETICAL_BANNER
from jtl.config import PROJECT_ROOT, AppConfig, load_config
from jtl.errors import JTLError
from jtl.market_data.models import BarSeries


def _cfg(path: str | None) -> AppConfig:
    if path is None:
        default = PROJECT_ROOT / "config.yaml"
        return load_config(default if default.exists() else PROJECT_ROOT / "config.example.yaml")
    return load_config(path)


def _load_series(cfg: AppConfig, csv: str | None, tr_csv: str | None) -> tuple[BarSeries, BarSeries | None]:
    from jtl.market_data.sample import synthetic_pair
    from jtl.market_data.store import load_csv, save_csv

    if csv:
        return load_csv(csv), (load_csv(tr_csv) if tr_csv else None)
    if cfg.data.provider == "csv":
        return load_csv(cfg.resolve(cfg.data.csv_path)), None
    if cfg.data.provider == "alpaca":
        base = PROJECT_ROOT / "data" / "alpaca"
        return load_csv(base / f"{cfg.strategy.symbol}_split.csv"), load_csv(base / f"{cfg.strategy.symbol}_all.csv")
    price, tr = synthetic_pair(cfg.strategy.symbol)
    sample_dir = PROJECT_ROOT / "data" / "sample"
    save_csv(price, sample_dir / f"{cfg.strategy.symbol}_synthetic.csv")
    save_csv(tr, sample_dir / f"{cfg.strategy.symbol}_synthetic_tr.csv")
    return price, tr


def cmd_sim(a: argparse.Namespace) -> int:
    from jtl import research
    from jtl.analytics import buy_and_hold, cash_benchmark, strategy_metrics
    from jtl.reports import write_report
    from jtl.simulator.engine import run_replay
    from jtl.storage.db import Storage

    cfg = _cfg(a.config)
    price, tr = _load_series(cfg, a.csv, a.tr_csv)
    ins, holdout = research.split(
        price, holdout_fraction=cfg.data.holdout_fraction, min_years=cfg.data.min_history_years
    )
    notes = [f"Data provenance: {price.provenance.label}"]
    if a.final_holdout:
        series = holdout.open_for_final_evaluation(a.final_holdout)
        # warm-up bars come from before the holdout, but only holdout sessions are traded
        warm = BarSeries(
            symbol=price.symbol,
            provenance=price.provenance,
            bars=tuple(b for b in price.bars if b.session < holdout.first_session)[-cfg.strategy.slow_window :]
            + series.bars,
        )
        series_for_run, start = warm, holdout.first_session
        notes.append(f"FINAL out-of-sample evaluation opened: {a.final_holdout!r}. Do not re-tune after this.")
        period = "holdout"
    else:
        series_for_run, start = ins.series, ins.series.bars[0].session
        notes.append(f"In-sample only. Held-out data from {holdout.first_session} was NOT used.")
        period = "in-sample"
    name = a.name or f"sim-{period}-{dt.datetime.now():%Y%m%d-%H%M%S}"
    db = PROJECT_ROOT / "var" / "runs" / f"{name}.db"
    run = run_replay(cfg, series_for_run, db, start=start)
    with Storage(db) as st:
        strat = strategy_metrics(st)
    s0, s1 = strat.start, strat.end
    metrics = [strat, buy_and_hold(price, s0, s1, cfg.simulator.starting_cash, "Buy & hold - price-only")]
    if tr is not None:
        metrics.append(buy_and_hold(tr, s0, s1, cfg.simulator.starting_cash, "Buy & hold - total return (dividends)"))
    else:
        notes.append("Total-return benchmark unavailable (no dividend-adjusted series supplied).")
    metrics.append(cash_benchmark(s0, s1, cfg.simulator.starting_cash))
    md, _js = write_report(PROJECT_ROOT / "reports" / "out", name, run, price, metrics, notes)
    print(HYPOTHETICAL_BANNER)
    print(f"Data: {price.provenance.label}")
    print(f"Period: {s0} -> {s1} ({period}); sessions={run.sessions}; halted={run.halted}")
    for m in metrics:
        print(f"  {m.label:45s} end={m.end_value:>10.2f}  ret={m.total_return:+7.2%}  maxDD={m.max_drawdown:7.2%}")
    print(f"Journal: {run.journal_events} events, head {run.journal_head[:16]}...")
    print(f"Report: {md}\nLedger DB: {db}")
    return 0


def cmd_compare(a: argparse.Namespace) -> int:
    from jtl import research
    from jtl.simulator.compare import run_comparison
    from jtl.strategy import default_lineup

    cfg = _cfg(a.config)
    price, tr = _load_series(cfg, a.csv, a.tr_csv)
    ins, holdout = research.split(
        price, holdout_fraction=cfg.data.holdout_fraction, min_years=cfg.data.min_history_years
    )
    if a.final_holdout:
        held = holdout.open_for_final_evaluation(a.final_holdout)
        hist = tuple(b for b in price.bars if b.session < holdout.first_session)[-400:]
        series = BarSeries(symbol=price.symbol, provenance=price.provenance, bars=hist + held.bars)
        period = "out-of-sample (final, opened once)"
    else:
        series, period = ins.series, "in-sample"
    cash = a.cash if a.cash is not None else cfg.simulator.starting_cash
    name = a.name or f"compare-{dt.datetime.now():%Y%m%d-%H%M%S}"
    out = PROJECT_ROOT / "var" / "compare" / name
    board = run_comparison(
        cfg, series, out, bots=default_lineup(cfg.strategy.symbol), cash=cash, total_return=tr, period_label=period
    )
    if a.final_holdout:
        # bots start after the 400 warm-up bars, which all lie before the holdout
        assert board["start"] >= holdout.first_session.isoformat()
    print(HYPOTHETICAL_BANNER)
    print(f"Data: {board['data_label']}  |  {period}: {board['start']} -> {board['end']}  |  cash per bot ${cash:,.2f}")
    for r in board["bots"]:
        print(
            f"  #{r['rank']} {r['title']:38s} end=${r['end_value']:>9.2f}  ret={r['total_return']:+7.2%}  "
            f"maxDD={r['max_drawdown']:7.2%}  trades={r['trades']}"
        )
    for m in board["benchmarks"]:
        print(f"     {m['label']:60s} end=${m['end_value']:>9.2f}  ret={m['total_return']:+7.2%}")
    print(f"Leaderboard: {out / 'leaderboard.md'}")
    return 0


def cmd_gate(a: argparse.Namespace) -> int:
    from jtl.market_data.sample import synthetic_pair
    from jtl.safety.gate import write_gate
    from jtl.simulator.engine import run_replay

    print("Running safety test-suite ...")
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=PROJECT_ROOT, check=False)
    sim_ok, detail = False, ""
    try:
        cfg = load_config(data={})
        price, _ = synthetic_pair("SPY", start=dt.date(2016, 1, 4), end=dt.date(2019, 12, 31))
        with tempfile.TemporaryDirectory() as td:
            r1 = run_replay(cfg, price, Path(td) / "a.db")
            r2 = run_replay(cfg, price, Path(td) / "b.db")
        sim_ok = r1.journal_head == r2.journal_head and not r1.halted and r1.sessions > 500
        detail = (
            f"sessions={r1.sessions} head={r1.journal_head[:16]} deterministic={r1.journal_head == r2.journal_head}"
        )
    except JTLError as e:
        detail = f"simulation failed: {e}"
    p = write_gate(tests.returncode == 0, sim_ok, {"sim": detail})
    print(f"tests_passed={tests.returncode == 0} sim_passed={sim_ok} ({detail})\nGate record: {p}")
    return 0 if tests.returncode == 0 and sim_ok else 1


def cmd_paper_status(_: argparse.Namespace) -> int:
    from jtl.safety.gate import paper_trading_allowed

    ok, reasons = paper_trading_allowed()
    print("Paper trading allowed:", ok)
    for r in reasons:
        print(" -", r)
    return 0


def cmd_fetch(a: argparse.Namespace) -> int:
    from jtl.market_data.alpaca import AlpacaDailyBars
    from jtl.market_data.models import Adjustment
    from jtl.market_data.store import save_csv
    from jtl.market_data.validation import check_sufficient, validate_series

    cfg = _cfg(a.config)
    sym = cfg.strategy.symbol
    start, end = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    client = AlpacaDailyBars(feed=cfg.data.alpaca_feed)
    try:
        for adj in (Adjustment.SPLIT, Adjustment.ALL):
            s = client.fetch(sym, start, end, adj)
            rep = validate_series(s, allowlist=cfg.symbols, max_abs_daily_return=cfg.data.max_abs_daily_return)
            check_sufficient(s, cfg.data.min_history_years)
            p = save_csv(s, PROJECT_ROOT / "data" / "alpaca" / f"{sym}_{adj.value}.csv")
            print(
                f"{adj.value}: {len(s)} bars {s.bars[0].session}..{s.bars[-1].session}; issues={len(rep.issues)} -> {p}"
            )
            if not rep.ok:
                print("  DATA ISSUES - research must stop until resolved:")
                for i in rep.issues[:20]:
                    print(f"   {i.session} {i.kind}: {i.detail}")
    finally:
        client.close()
    return 0


def _db(a: argparse.Namespace) -> Path:
    return Path(a.db) if a.db else PROJECT_ROOT / "var" / "jtl.db"


def cmd_verify(a: argparse.Namespace) -> int:
    from jtl.storage.db import Storage

    with Storage(_db(a)) as st:
        n, head = st.verify_journal()
    print(f"journal OK: {n} events, head {head}")
    return 0


def cmd_backup(a: argparse.Namespace) -> int:
    from jtl.storage.db import Storage

    cfg = _cfg(a.config)
    with Storage(_db(a)) as st:
        print("backup written:", st.backup(cfg.resolve(cfg.storage.backup_dir)))
    return 0


def cmd_breakers(a: argparse.Namespace) -> int:
    from jtl.risk.breakers import BreakerBook
    from jtl.storage.db import Storage

    with Storage(_db(a)) as st:
        for b in BreakerBook(st).all():
            print(f"{b.name:12s} latched={b.latched} since={b.tripped_session} until={b.until_session} :: {b.reason}")
    return 0


def cmd_reset(a: argparse.Namespace) -> int:
    from jtl.risk.breakers import RESET_PHRASE, BreakerBook
    from jtl.storage.db import Storage

    print(f"To reset breaker '{a.name}', type exactly:\n  {RESET_PHRASE}")
    phrase = input("> ")
    with Storage(_db(a)) as st:
        BreakerBook(st).manual_reset(a.name, phrase, a.operator, dt.datetime.now(dt.UTC).isoformat())
    print("breaker reset (journaled).")
    return 0


def cmd_dashboard(a: argparse.Namespace) -> int:
    from jtl.dashboard import serve

    cfg = _cfg(a.config)
    print(f"Dashboard (read-only) on http://{cfg.dashboard.host}:{cfg.dashboard.port}  - Ctrl+C to stop")
    compare_dir = None
    if a.compare:
        compare_dir = Path(a.compare)
        if not compare_dir.is_absolute():
            compare_dir = PROJECT_ROOT / "var" / "compare" / a.compare
    serve(_db(a), cfg.dashboard.host, cfg.dashboard.port, compare_dir=compare_dir)
    return 0


def cmd_next_run(a: argparse.Namespace) -> int:
    from jtl.scheduler import next_run_time

    cfg = _cfg(a.config)
    print(next_run_time(dt.datetime.now(dt.UTC), cfg.data.bar_confirmation_delay_minutes).isoformat())
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="jtl", description="Jarvis Trading Lab - PAPER-ONLY research & simulation")
    p.add_argument("--config")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sim", help="deterministic local replay (in-sample by default)")
    s.add_argument("--csv")
    s.add_argument("--tr-csv")
    s.add_argument("--name")
    s.add_argument("--final-holdout", metavar="REASON", help="open the sealed out-of-sample slice ONCE")
    s.set_defaults(fn=cmd_sim)
    c = sub.add_parser("compare", help="run every bot on its own virtual account and rank them")
    c.add_argument("--cash", type=float)
    c.add_argument("--csv")
    c.add_argument("--tr-csv")
    c.add_argument("--name")
    c.add_argument("--final-holdout", metavar="REASON", help="open the sealed out-of-sample slice ONCE")
    c.set_defaults(fn=cmd_compare)
    sub.add_parser("gate", help="run tests + local simulation and record the paper gate").set_defaults(fn=cmd_gate)
    sub.add_parser("paper-status", help="show why paper trading is (not) allowed").set_defaults(fn=cmd_paper_status)
    f = sub.add_parser("fetch-data", help="fetch Alpaca daily bars (needs YOUR paper/data keys in env)")
    f.add_argument("--start", required=True)
    f.add_argument("--end", required=True)
    f.set_defaults(fn=cmd_fetch)
    for name, fn in (
        ("verify-journal", cmd_verify),
        ("backup", cmd_backup),
        ("breakers", cmd_breakers),
        ("dashboard", cmd_dashboard),
    ):
        x = sub.add_parser(name)
        x.add_argument("--db")
        if name == "dashboard":
            x.add_argument("--compare", help="leaderboard folder name under var/compare")
        x.set_defaults(fn=fn)
    r = sub.add_parser("reset-breaker", help="HUMAN-ONLY reset of a latched breaker")
    r.add_argument("--db")
    r.add_argument("--name", required=True)
    r.add_argument("--operator", required=True)
    r.set_defaults(fn=cmd_reset)
    sub.add_parser("next-run").set_defaults(fn=cmd_next_run)
    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except JTLError as e:
        print(f"REFUSED / STOPPED ({type(e).__name__}): {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
