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
from jtl.dashboard.page import render_board
from jtl.errors import ConfigRejected
from jtl.market_data.live import LivePrice, market_open_now

MAX_LIVE_MOVE = 0.15  # ignore a live price more than 15% away from the last close (bad tick)


def _ro(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)


def create_app(
    db_path: str | Path | None = None, compare_dir: str | Path | None = None, live: LivePrice | None = None
) -> FastAPI:
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

    @app.get("/api/live")
    def live_data() -> dict:
        """DISPLAY ONLY: today's value of each bot at the latest real-time price. Never trades."""
        b = compare_data()
        out: dict = {"hypothetical": True, "ok": False, "market_open": market_open_now(), "bots": {}}
        if live is None or not b.get("bots") or not str(b.get("period", "")).startswith("FORWARD"):
            out["reason"] = "live view only for the forward test"
            return out
        quote, err = live.get()
        last_close = b.get("last_close")
        if quote is None:
            out["reason"] = err or "no price"
            return out
        if last_close and abs(quote.price / float(last_close) - 1) > MAX_LIVE_MOVE:
            out["reason"] = "price looks wrong - ignored"
            return out
        cash = float(b["starting_cash"])
        for r in b["bots"]:
            qty = float(r.get("qty_now") or 0.0)
            c = r.get("cash_now")
            value = (float(c) + qty * quote.price) if (qty and c is not None) else float(r["end_value"])
            out["bots"][r["name"]] = {"value": round(value, 2), "change": value / cash - 1, "live": bool(qty)}
        out.update(ok=True, price=quote.price, time=quote.time.isoformat(), source=quote.source, last_close=last_close)
        return out

    @app.get("/compare", response_class=HTMLResponse)
    def compare_page() -> str:
        b = compare_data()
        if not b.get("bots"):
            return "<p>No comparison loaded.</p>"
        return render_board(b)

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

    live = None
    if compare_dir is not None:
        board = Path(compare_dir) / "leaderboard.json"
        sym = json.loads(board.read_text(encoding="utf-8")).get("symbol", "SPY") if board.exists() else "SPY"
        live = LivePrice(sym)
    uvicorn.run(create_app(db_path, compare_dir, live), host=host, port=port, log_level="warning")
