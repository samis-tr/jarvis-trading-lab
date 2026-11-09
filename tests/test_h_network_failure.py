"""H. Failed networking never sends a live order (and never sends any order at all)."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest

from jtl.errors import DataError, PaperTradingNotEnabled
from jtl.market_data.alpaca import BARS_URL, AlpacaDailyBars
from jtl.market_data.models import Adjustment


def _client(handler):
    return AlpacaDailyBars(transport=httpx.MockTransport(handler), key_id="PKTEST000", secret="SECRETTEST000")


@pytest.mark.parametrize("exc", [httpx.ConnectError("down"), httpx.ReadTimeout("slow"), httpx.RemoteProtocolError("x")])
def test_network_errors_become_data_errors_and_contact_nothing_else(exc):
    seen = []

    def handler(request):
        seen.append(request.url.host)
        raise exc

    c = _client(handler)
    with pytest.raises(DataError):
        c.fetch("SPY", dt.date(2020, 1, 1), dt.date(2020, 2, 1), Adjustment.SPLIT)
    assert set(seen) == {"data.alpaca.markets"}


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_http_errors_fail_closed(status):
    c = _client(lambda r: httpx.Response(status, json={"message": "nope"}))
    with pytest.raises(DataError):
        c.fetch("SPY", dt.date(2020, 1, 1), dt.date(2020, 2, 1), Adjustment.SPLIT)


def test_malformed_payload_fails_closed():
    c = _client(lambda r: httpx.Response(200, json={"bars": {"SPY": [{"t": "x", "o": "a"}]}}))
    with pytest.raises(DataError):
        c.fetch("SPY", dt.date(2020, 1, 1), dt.date(2020, 2, 1), Adjustment.SPLIT)


def test_mocked_alpaca_parse_with_paging_and_tz():
    pages = {
        None: {
            "bars": {"SPY": [{"t": "2024-03-04T05:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10}]},
            "next_page_token": "p2",
        },
        "p2": {
            "bars": {"SPY": [{"t": "2024-03-05T05:00:00Z", "o": 1.5, "h": 2, "l": 1, "c": 1.8, "v": 9}]},
            "next_page_token": None,
        },
    }
    reqs = []

    def handler(request):
        reqs.append(request)
        assert str(request.url).startswith(BARS_URL)
        assert request.url.params["adjustment"] == "all" and request.url.params["timeframe"] == "1Day"
        return httpx.Response(200, json=pages[request.url.params.get("page_token")])

    s = _client(handler).fetch("SPY", dt.date(2024, 3, 1), dt.date(2024, 3, 6), Adjustment.ALL)
    assert [b.session for b in s.bars] == [dt.date(2024, 3, 4), dt.date(2024, 3, 5)]
    assert s.provenance.source.value == "ALPACA" and len(reqs) == 2


def test_missing_keys_refused_without_any_request():
    with pytest.raises(DataError):
        AlpacaDailyBars(transport=httpx.MockTransport(lambda r: pytest.fail("network used")))


def test_paper_broker_cannot_be_constructed_so_no_order_can_be_sent():
    from jtl.alpaca_paper import AlpacaPaperBroker

    with pytest.raises(PaperTradingNotEnabled):
        AlpacaPaperBroker(transport=httpx.MockTransport(lambda r: pytest.fail("order sent")))


def test_secrets_never_reach_journal(storage, monkeypatch):
    from jtl.errors import SecretLeak

    monkeypatch.setenv("APCA_API_SECRET_KEY", "super-secret-value-123")
    with pytest.raises(SecretLeak):
        storage.record("t", "x", {"note": "leak super-secret-value-123"})
    with pytest.raises(SecretLeak):
        storage.record("t", "x", {"api_key": "abc"})
    assert storage.query("SELECT COUNT(*) FROM events")[0][0] == 0
