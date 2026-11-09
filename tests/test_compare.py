"""Bot comparison: isolation, fairness, determinism, labelling; new strategies have no look-ahead."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from jtl import HYPOTHETICAL_BANNER
from jtl.dashboard import create_app
from jtl.simulator.compare import run_comparison
from jtl.strategy import AlwaysLong, Momentum, SmaTrend, Strategy, Target, default_lineup
from tests.conftest import make_series


def test_all_bots_satisfy_interface_and_have_unique_names():
    bots = default_lineup("SPY")
    assert all(isinstance(b, Strategy) for b in bots)
    assert len({b.name for b in bots}) == len(bots)


@pytest.mark.parametrize("bot", [Momentum("SPY", 20), AlwaysLong("SPY"), SmaTrend("SPY", 5, 20)])
def test_new_bots_ignore_future_and_refuse_future_views(bot, synth):
    t = synth.bars[300].session
    assert bot.signal(synth.upto(t), t) == bot.signal(synth.upto(t), t)
    with pytest.raises(AssertionError):
        bot.signal(synth.upto(synth.bars[301].session), t)


def test_momentum_direction():
    up = make_series([100 + i for i in range(30)])
    down = make_series([200 - i for i in range(30)])
    assert Momentum("SPY", 20).signal(up, up.bars[-1].session).target is Target.LONG
    assert Momentum("SPY", 20).signal(down, down.bars[-1].session).target is Target.FLAT


def test_comparison_is_fair_isolated_deterministic_and_hypothetical(tmp_path, cfg, synth):
    bots = [SmaTrend("SPY", 20, 100), Momentum("SPY", 63), AlwaysLong("SPY")]
    a = run_comparison(cfg, synth, tmp_path / "a", bots=bots, cash=100, total_return=None)
    b = run_comparison(cfg, synth, tmp_path / "b", bots=bots, cash=100, total_return=None)
    assert [r["end_value"] for r in a["bots"]] == [r["end_value"] for r in b["bots"]]
    assert a["hypothetical"] is True and a["disclaimer"] == HYPOTHETICAL_BANNER and a["data_is_real"] is False
    assert {r["start"] for r in a["bots"]} == {a["start"]}  # same trading start for all
    assert all(r["start_value"] == pytest.approx(100) for r in a["bots"])
    assert [r["end_value"] for r in a["bots"]] == sorted((r["end_value"] for r in a["bots"]), reverse=True)
    for bot in bots:  # every bot has its own ledger
        assert (tmp_path / "a" / f"{bot.name}.db").exists()
    saved = json.loads((tmp_path / "a" / "leaderboard.json").read_text(encoding="utf-8"))
    assert saved["bots"][0]["name"] == a["bots"][0]["name"]
    with pytest.raises(FileExistsError):
        run_comparison(cfg, synth, tmp_path / "a", bots=bots, cash=100)


def test_leaderboard_page_is_read_only(tmp_path, cfg, synth):
    run_comparison(cfg, synth, tmp_path / "c", bots=[AlwaysLong("SPY")], cash=100)
    client = TestClient(create_app(None, tmp_path / "c"))
    page = client.get("/").text
    assert "Bot leaderboard" in page and HYPOTHETICAL_BANNER in page
    assert client.get("/api/compare").json()["hypothetical"] is True
    assert client.post("/api/compare", json={}).status_code == 405
