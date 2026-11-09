"""Read-only localhost dashboard (FastAPI). No order, reset or config endpoints exist."""

from __future__ import annotations

import html
import json
import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from jtl import HYPOTHETICAL_BANNER
from jtl.config import LOCALHOST_HOSTS
from jtl.errors import ConfigRejected


def _ro(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)


COLORS = ["#4e9af1", "#f28e2b", "#59a14f", "#e15759", "#b07aa1", "#edc948", "#76b7b2", "#ff9da7"]
STYLE = """body{font-family:system-ui;margin:16px;background:#111;color:#eee;max-width:1100px}
.w{background:#c80;color:#000;padding:8px;border-radius:4px}table{border-collapse:collapse;width:100%;font-size:14px}
td,th{padding:4px 8px;border-bottom:1px solid #333;text-align:right}td:nth-child(2),th:nth-child(2){text-align:left}
a{color:#8cf}.scroll{overflow-x:auto}svg{width:100%;height:auto;background:#181818;border-radius:4px}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}"""


def _chart(bots: list[dict], cash: float) -> str:
    curves = [[v for _, v in b["curve"]] for b in bots]
    allv = [v for c in curves for v in c] + [cash]
    lo, hi = min(allv), max(allv)
    span = (hi - lo) or 1.0
    w, h, pad = 1000, 320, 30
    out = []
    base_y = h - pad - (cash - lo) / span * (h - 2 * pad)
    out.append(
        f'<line x1="{pad}" x2="{w - pad}" y1="{base_y:.1f}" y2="{base_y:.1f}" stroke="#555" stroke-dasharray="4"/>'
    )
    out.append(f'<text x="{pad}" y="{base_y - 4:.1f}" fill="#888" font-size="12">start ${cash:,.0f}</text>')
    for i, c in enumerate(curves):
        n = max(len(c) - 1, 1)
        pts = " ".join(
            f"{pad + j / n * (w - 2 * pad):.1f},{h - pad - (v - lo) / span * (h - 2 * pad):.1f}"
            for j, v in enumerate(c)
        )
        out.append(f'<polyline fill="none" stroke="{COLORS[i % len(COLORS)]}" stroke-width="2" points="{pts}"/>')
    out.append(f'<text x="{pad}" y="{pad - 8}" fill="#888" font-size="12">${hi:,.2f}</text>')
    out.append(f'<text x="{pad}" y="{h - 8}" fill="#888" font-size="12">${lo:,.2f}</text>')
    return f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="equity curves">{"".join(out)}</svg>'


def create_app(db_path: str | Path | None = None, compare_dir: str | Path | None = None) -> FastAPI:
    db = Path(db_path) if db_path else Path("__none__.db")
    board_file = Path(compare_dir) / "leaderboard.json" if compare_dir else None
    app = FastAPI(
        title="Jarvis Trading Lab (read-only, paper/sim only)", docs_url=None, redoc_url=None, openapi_url=None
    )

    def q(sql: str, params: tuple = ()) -> list[tuple]:
        if not db.exists():
            return []
        with _ro(db) as c:
            return c.execute(sql, params).fetchall()

    @app.get("/api/status")
    def status() -> dict:
        eq = q("SELECT session, equity, cash FROM equity ORDER BY session DESC LIMIT 1")
        return {
            "hypothetical": True,
            "disclaimer": HYPOTHETICAL_BANNER,
            "mode": "LOCAL_SIM",
            "db": db.name,
            "latest": dict(zip(("session", "equity", "cash"), eq[0], strict=True)) if eq else None,
            "positions": [
                dict(symbol=s, qty=qq, stop=st) for s, qq, st in q("SELECT symbol, qty, stop_price FROM positions")
            ],
            "breakers": [
                dict(name=n, latched=bool(lat), reason=r, until=u)
                for n, lat, r, u in q("SELECT name, latched, reason, until_session FROM breakers")
            ],
        }

    @app.get("/api/equity")
    def equity() -> list[dict]:
        return [dict(session=s, equity=float(e)) for s, e in q("SELECT session, equity FROM equity ORDER BY session")]

    @app.get("/api/events")
    def events(limit: int = 50) -> list[dict]:
        limit = max(1, min(limit, 500))
        return [
            dict(seq=s, ts=t, kind=k, payload=p)
            for s, t, k, p in q("SELECT seq, ts, kind, payload FROM events ORDER BY seq DESC LIMIT ?", (limit,))
        ]

    @app.get("/api/compare")
    def compare_data() -> dict:
        if not board_file or not board_file.exists():
            return {"hypothetical": True, "bots": [], "benchmarks": []}
        return json.loads(board_file.read_text(encoding="utf-8"))

    @app.get("/compare", response_class=HTMLResponse)
    def compare_page() -> str:
        b = compare_data()
        if not b.get("bots"):
            return "<p>No comparison loaded.</p>"
        e = html.escape
        rows = "".join(
            f"<tr><td>{r['rank']}</td><td><span class='sw' style='background:{COLORS[i % len(COLORS)]}'></span>"
            f"{e(r['title'])}</td><td>${r['end_value']:,.2f}</td><td>{r['total_return']:+.2%}</td>"
            f"<td>{r['cagr']:+.2%}</td><td>{r['max_drawdown']:.2%}</td><td>{r['trades']}</td>"
            f"<td>{e(', '.join(r['breakers']) or '-')}</td></tr>"
            for i, r in enumerate(b["bots"])
        )
        bench = "".join(
            f"<tr><td></td><td>{e(m['label'])}</td><td>${m['end_value']:,.2f}</td><td>{m['total_return']:+.2%}</td>"
            f"<td>{m['cagr']:+.2%}</td><td>{m['max_drawdown']:.2%}</td><td>-</td><td>-</td></tr>"
            for m in b["benchmarks"]
        )
        notes = "".join(f"<li>{e(n)}</li>" for n in b["notes"])
        return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1"><title>Bot leaderboard</title><style>{STYLE}</style></head><body>
<div class="w"><b>{e(b["disclaimer"])}</b></div>
<h1>Bot leaderboard</h1>
<p>Data: <b>{e(b["data_label"])}</b> &middot; {e(b["period"])}: {e(b["start"])} &rarr; {e(b["end"])}
 &middot; virtual cash per bot: <b>${b["starting_cash"]:,.2f}</b></p>
<div class="scroll"><table><tr><th>#</th><th>Bot</th><th>End value</th><th>Return</th><th>CAGR</th>
<th>Max drawdown</th><th>Trades</th><th>Breakers</th></tr>{rows}
<tr><th colspan="8" style="text-align:left;padding-top:14px">Benchmarks (no risk limits, no costs)</th></tr>{bench}
</table></div><h3>Equity of each bot</h3>{_chart(b["bots"], b["starting_cash"])}<ul>{notes}</ul></body></html>"""

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        if board_file is not None:
            return compare_page()
        st = status()
        rows = "".join(
            f"<tr><td>{html.escape(e['kind'])}</td><td>{html.escape(e['ts'])}</td>"
            f"<td><code>{html.escape(e['payload'][:160])}</code></td></tr>"
            for e in events(30)
        )
        brk = "".join(f"<li>{html.escape(b['name'])}: {html.escape(b['reason'])}</li>" for b in st["breakers"])
        latest = st["latest"] or {}
        return f"""<!doctype html><html><head><meta charset="utf-8"><title>Jarvis Trading Lab</title>
<style>body{{font-family:system-ui;margin:24px;background:#111;color:#eee}}.b{{background:#5a1;color:#000;
padding:8px}}.w{{background:#c80;color:#000;padding:8px}}td{{padding:2px 8px;border-bottom:1px solid #333}}</style>
</head><body><div class="w"><b>{html.escape(HYPOTHETICAL_BANNER)}</b></div>
<h1>Jarvis Trading Lab - LOCAL_SIM (read-only)</h1>
<p>Latest session: {html.escape(str(latest.get("session", "-")))} - equity {html.escape(str(latest.get("equity", "-")))}
 - cash {html.escape(str(latest.get("cash", "-")))}</p>
<h3>Breakers</h3><ul>{brk or "<li>none</li>"}</ul>
<h3>Recent journal events</h3><table>{rows}</table></body></html>"""

    return app


def serve(
    db_path: str | Path | None, host: str = "127.0.0.1", port: int = 8765, compare_dir: str | Path | None = None
) -> None:
    if host not in LOCALHOST_HOSTS:
        raise ConfigRejected("dashboard binds to localhost only")
    import uvicorn

    uvicorn.run(create_app(db_path, compare_dir), host=host, port=port, log_level="warning")
