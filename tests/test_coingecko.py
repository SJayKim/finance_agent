import json

import httpx

from app.pipeline.coingecko import _COINS_LIST_URL, _parse_coins, fetch_universe_coins

_SAMPLE = json.dumps(
    [
        {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin"},
        {"id": "ondo-finance", "symbol": "ondo", "name": "Ondo"},
        {"id": "some-random-shitcoin", "symbol": "btc", "name": "Fake Bitcoin"},
    ]
).encode("utf-8")


def test_parse_filters_to_universe_and_uppercases() -> None:
    pairs = _parse_coins(_SAMPLE)
    assert pairs == [("Bitcoin", "BTC"), ("Ondo", "ONDO")]


def test_fetch_calls_coins_list_and_parses() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, content=_SAMPLE)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        pairs = fetch_universe_coins(client=client)

    assert seen["url"] == _COINS_LIST_URL
    assert pairs == [("Bitcoin", "BTC"), ("Ondo", "ONDO")]
