import json

import httpx
import pytest

from app.config import settings
from app.pipeline.sec import SECError, _parse_company_tickers, fetch_company_tickers

_SAMPLE = json.dumps(
    {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
        "2": {"cik_str": 1, "ticker": " ", "title": "No Ticker Co"},
    }
).encode("utf-8")


def test_parse_filters_empty_ticker() -> None:
    pairs = _parse_company_tickers(_SAMPLE)
    assert pairs == [("Apple Inc.", "AAPL"), ("MICROSOFT CORP", "MSFT")]


def test_fetch_sends_user_agent_and_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sec_edgar_user_agent", "finance-agent test@example.com")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers.get("User-Agent")
        return httpx.Response(200, content=_SAMPLE)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        pairs = fetch_company_tickers(client=client)

    assert seen["ua"] == "finance-agent test@example.com"
    assert pairs == [("Apple Inc.", "AAPL"), ("MICROSOFT CORP", "MSFT")]


def test_fetch_no_user_agent_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sec_edgar_user_agent", None)
    with pytest.raises(ValueError):
        fetch_company_tickers()


def test_fetch_non_json_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON 아닌 차단 페이지(403 HTML 본문) -> SECError."""
    monkeypatch.setattr(settings, "sec_edgar_user_agent", "ua")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>Access Denied</html>")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SECError):
            fetch_company_tickers(client=client)
