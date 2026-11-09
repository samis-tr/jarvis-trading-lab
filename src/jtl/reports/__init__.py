"""Markdown + JSON run reports. Always carry the HYPOTHETICAL banner and the data-provenance label."""

from __future__ import annotations

import json
from pathlib import Path

from jtl import HYPOTHETICAL_BANNER
from jtl.analytics import Metrics, fmt_money
from jtl.market_data.models import BarSeries
from jtl.safety.secrets import assert_no_secrets, redact
from jtl.simulator.engine import ReplayResult


def _row(m: Metrics) -> str:
    sharpe = f"{m.sharpe:.2f}" if m.sharpe is not None else "n/a"
    return (
        f"| {m.label} | {fmt_money(m.start_value)} | {fmt_money(m.end_value)} | {m.total_return:+.2%} | "
        f"{m.cagr:+.2%} | {m.max_drawdown:.2%} | {sharpe} | {m.trades} |"
    )


def write_report(
    out_dir: str | Path,
    name: str,
    run: ReplayResult,
    series: BarSeries,
    metrics: list[Metrics],
    extra_notes: list[str] | None = None,
) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "hypothetical": True,
        "disclaimer": HYPOTHETICAL_BANNER,
        "data_label": series.provenance.label,
        "data_source": series.provenance.source.value,
        "data_is_real": series.provenance.is_real,
        "sessions": run.sessions,
        "journal_events": run.journal_events,
        "journal_head": run.journal_head,
        "halted": run.halted,
        "validation_issues": [
            dict(session=i.session.isoformat(), kind=i.kind, detail=i.detail) for i in run.validation.issues[:50]
        ],
        "metrics": [m.as_dict() for m in metrics],
        "notes": extra_notes or [],
    }
    assert_no_secrets(payload)
    jp = out / f"{name}.json"
    jp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        f"# Simulation report - {name}",
        "",
        f"> **{HYPOTHETICAL_BANNER}**",
        "",
        f"- **Data:** {series.provenance.label}"
        + ("" if series.provenance.is_real else " - results say NOTHING about real markets."),
        f"- **Sessions replayed:** {run.sessions}  |  **Journal events:** {run.journal_events}",
        f"- **Journal head hash:** `{run.journal_head}`",
        f"- **System halted during run:** {'YES' if run.halted else 'no'}",
        f"- **Data validation issues:** {len(run.validation.issues)}",
        "",
        "| Series | Start | End | Total return | CAGR | Max DD | Sharpe | Trades |",
        "|---|---|---|---|---|---|---|---|",
        *[_row(m) for m in metrics],
        "",
        "## Notes",
        *[f"- {n}" for m in metrics for n in m.notes if n],
        *[f"- {n}" for n in (extra_notes or [])],
        "- Gap risk: a protective stop that is gapped through fills at the open, so a single trade can lose more"
        " than the 0.5% risk budget.",
        "- No strategy here is claimed to be profitable. Past (or simulated) performance does not predict the future.",
    ]
    mp = out / f"{name}.md"
    mp.write_text(redact("\n".join(lines) + "\n"), encoding="utf-8")
    return mp, jp
