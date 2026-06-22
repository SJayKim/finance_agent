import json
from datetime import timezone

import httpx
import pytest

from app.collector.finnhub import (
    FinnhubConnector,
    FinnhubError,
    normalize,
    parse_news,
)
from app.config import settings

# Finnhub /news?category=crypto 응답: 아이템 dict 리스트. 2번째는 datetime 0 → published_at None.
_SAMPLE = json.dumps(
    [
        {
            "id": 7654321,
            "headline": "Bitcoin tops $100K for the first time",
            "summary": "BTC surges past 100,000.",
            "url": "https://finnhub.io/news/btc-100k",
            "datetime": 1750292400,  # 2025-06-19 (Unix epoch seconds)
            "source": "CoinDesk",
            "category": "crypto",
            "image": "https://example.com/btc.png",
        },
        {
            "id": 7654322,
            "headline": "Ethereum upgrade ships",
            "summary": "The merge follow-up landed.",
            "url": "https://finnhub.io/news/eth-upgrade",
            "datetime": 0,  # 누락/0 → published_at None
            "source": "Decrypt",
            "category": "crypto",
            "image": "",
        },
    ]
).encode("utf-8")


def test_parse_news_extracts_items() -> None:
    items = parse_news(json.loads(_SAMPLE))
    assert len(items) == 2
    assert items[0]["id"] == 7654321
    assert items[0]["headline"] == "Bitcoin tops $100K for the first time"


def test_normalize_parses_unix_datetime_utc_and_body_none() -> None:
    items = parse_news(json.loads(_SAMPLE))

    doc = normalize(items[0])
    assert doc.external_id == str(items[0]["id"])
    assert doc.title == "Bitcoin tops $100K for the first time"
    assert doc.summary == "BTC surges past 100,000."
    assert doc.body is None  # P5: 본문 grounding 불가
    assert doc.lang == "en"
    assert doc.url == "https://finnhub.io/news/btc-100k"
    assert doc.published_at is not None
    assert doc.published_at.tzinfo == timezone.utc

    # datetime 0 → published_at None
    doc0 = normalize(items[1])
    assert doc0.published_at is None
    assert doc0.body is None


def test_fetch_sends_token_and_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "finnhub_api_key", "test-token")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.url.params.get("token")
        seen["category"] = request.url.params.get("category")
        return httpx.Response(200, content=_SAMPLE)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        conn = FinnhubConnector(client=client)
        items = list(conn.fetch())

    assert seen["token"] == "test-token"
    assert seen["category"] == "crypto"
    assert len(items) == 2
    assert items[0]["id"] == 7654321


def test_fetch_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "finnhub_api_key", None)
    conn = FinnhubConnector()
    with pytest.raises(FinnhubError):
        list(conn.fetch())
