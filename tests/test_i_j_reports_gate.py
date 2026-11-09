"""I. Performance is marked hypothetical.  J. Paper trading cannot start until sim + tests pass."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from jtl import HYPOTHETICAL_BANNER
from jtl.analytics import buy_and_hold, cash_benchmark, strategy_metrics
from jtl.dashboard import create_app
from jtl.reports import write_report
from jtl.safety import gate
from jtl.simulator.engine import run_replay
from jtl.storage.db import Storage


def test_reports_and_metrics_are_marked_hypothetical(tmp_path, cfg, synth):
    run = run_replay(cfg, synth, tmp_path / "r.db")
    assert run.hypothetical is True
    with Storage(tmp_path / "r.db") as st:
        m = strategy_metrics(st)
    bh = buy_and_hold(synth, m.start, m.end, 1000, "B&H price-only")
    md, js = write_report(tmp_path / "out", "t", run, synth, [m, bh, cash_benchmark(m.start, m.end, 1000)])
    text = md.read_text(encoding="utf-8")
    assert HYPOTHETICAL_BANNER in text and "TEST FIXTURE DATA" in text
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["hypothetical"] is True and data["data_is_real"] is False
    assert all(x["hypothetical"] is True and x["disclaimer"] == HYPOTHETICAL_BANNER for x in data["metrics"])


def test_dashboard_is_read_only_and_labelled(tmp_path, cfg, synth):
    run_replay(cfg, synth, tmp_path / "r.db")
    client = TestClient(create_app(tmp_path / "r.db"))
    st = client.get("/api/status").json()
    assert st["hypothetical"] is True and st["mode"] == "LOCAL_SIM"
    assert HYPOTHETICAL_BANNER in client.get("/").text
    for path in ("/api/orders", "/api/reset", "/api/config"):
        assert client.post(path, json={}).status_code in (404, 405)
    assert client.post("/api/status").status_code == 405


def test_dashboard_refuses_non_localhost():
    import pytest

    from jtl.dashboard import serve
    from jtl.errors import ConfigRejected

    with pytest.raises(ConfigRejected):
        serve("x.db", host="0.0.0.0")


def test_gate_requires_tests_and_sim_and_current_source(tmp_path):
    g = tmp_path / "gate.json"
    ok, reasons = gate.paper_trading_allowed(g, phase4_enabled=True)
    assert not ok and any("no gate record" in r for r in reasons)
    for tests_ok, sim_ok in ((False, True), (True, False), (False, False)):
        gate.write_gate(tests_ok, sim_ok, {}, g)
        assert not gate.paper_trading_allowed(g, phase4_enabled=True)[0]
    gate.write_gate(True, True, {}, g)
    assert gate.paper_trading_allowed(g, phase4_enabled=True) == (True, [])
    data = json.loads(g.read_text())
    data["source_hash"] = "0" * 64
    g.write_text(json.dumps(data))
    ok, reasons = gate.paper_trading_allowed(g, phase4_enabled=True)
    assert not ok and any("source changed" in r for r in reasons)


def test_phase2_build_never_allows_paper_even_with_valid_gate(tmp_path):
    g = tmp_path / "gate.json"
    gate.write_gate(True, True, {}, g)
    ok, reasons = gate.paper_trading_allowed(g)
    assert not ok and any("Phase 4" in r for r in reasons)
