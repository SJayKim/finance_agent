import json

import httpx
import pytest

from app.pipeline.openfigi import NormalizedTicker, OpenFIGIError, OpenFIGIRateLimited, normalize


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_normalize_parses_ticker_and_sends_job() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json=[{"data": [{"ticker": "AAPL", "exchCode": "US", "name": "APPLE INC"}]}]
        )

    with _client(httpx.MockTransport(handler)) as client:
        result = normalize("TICKER", "AAPL", "US", client=client)

    assert result == NormalizedTicker(ticker="AAPL", exch_code="US", name="APPLE INC")
    assert seen["body"] == [{"idType": "TICKER", "idValue": "AAPL", "exchCode": "US"}]


def test_normalize_no_match_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"warning": "No identifier found."}])

    with _client(httpx.MockTransport(handler)) as client:
        assert normalize("TICKER", "NOPE", "US", client=client) is None


def test_normalize_retries_on_429_then_succeeds() -> None:
    calls = {"n": 0}
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json=[{"data": [{"ticker": "AAPL"}]}])

    with _client(httpx.MockTransport(handler)) as client:
        result = normalize("TICKER", "AAPL", "US", client=client, sleep=slept.append)

    assert result == NormalizedTicker(ticker="AAPL", exch_code=None, name=None)
    assert calls["n"] == 2
    assert slept == [2.0]


def test_normalize_raises_after_persistent_429() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "5"})

    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(OpenFIGIRateLimited) as exc:
            normalize("TICKER", "AAPL", "US", client=client, max_retries=1, sleep=lambda _s: None)

    assert exc.value.retry_after == 5.0


def test_normalize_error_body_raises() -> None:
    """200 응답에 error 키 → OpenFIGIError (no-match warning과 구분)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"error": "Invalid idType value: TICKER"}])

    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(OpenFIGIError):
            normalize("TICKER", "AAPL", "US", client=client)


def test_normalize_exchange_priority_picks_nyse_over_nasdaq() -> None:
    """복수 레코드 중 NYSE(UN)를 NASDAQ(UW)보다 우선 선택."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "data": [
                        {"ticker": "AAPL", "exchCode": "UW", "name": "APPLE INC"},
                        {"ticker": "AAPL", "exchCode": "UN", "name": "APPLE INC"},
                    ]
                }
            ],
        )

    with _client(httpx.MockTransport(handler)) as client:
        result = normalize("TICKER", "AAPL", "US", client=client)

    assert result == NormalizedTicker(ticker="AAPL", exch_code="UN", name="APPLE INC")


def test_normalize_timeout_returns_none() -> None:
    """네트워크 타임아웃 → None (호출자가 is_candidate=True로 처리)."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    with _client(httpx.MockTransport(handler)) as client:
        result = normalize("TICKER", "AAPL", "US", client=client)

    assert result is None
