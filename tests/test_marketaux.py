import json
from datetime import timezone

import httpx
import pytest

from app.collector.marketaux import (
    MarketauxConnector,
    MarketauxError,
    normalize,
    parse_news,
)
from app.config import settings

# 실제 /v1/news/all 응답 형태(2건). 첫 건은 description, 둘째는 description 없이 snippet만.
_SAMPLE = json.dumps(
    {
        "data": [
            {
                "uuid": "mx-1",
                "title": "Bitcoin tops $100K for the first time",
                "description": "BTC <b>surges</b> past 100,000.",
                "snippet": "ignored when description present",
                "url": "https://example.com/news/btc-100k",
                "published_at": "2026-06-22T09:00:00.000000Z",
                "source": "example.com",
                "entities": [{"symbol": "BTC", "sentiment_score": 0.8}],
            },
            {
                "uuid": "mx-2",
                "title": "Ethereum upgrade ships",
                "description": None,
                "snippet": "ETH mainnet upgrade goes live.",
                "url": "https://example.com/news/eth-upgrade",
                "published_at": "2026-06-22T10:15:00.000000Z",
                "source": "example.com",
                "entities": [{"symbol": "ETH"}],
            },
        ],
        "meta": {"found": 2, "returned": 2, "limit": 100, "page": 1},
    }
).encode("utf-8")


def test_parse_news_extracts_items() -> None:
    items = parse_news(json.loads(_SAMPLE))
    assert len(items) == 2
    assert items[0]["uuid"] == "mx-1"
    assert items[1]["uuid"] == "mx-2"


def test_normalize_parses_iso_pubdate_utc_and_body_none() -> None:
    items = parse_news(json.loads(_SAMPLE))
    doc = normalize(items[0])
    assert doc.external_id == "mx-1"
    assert doc.summary == "BTC surges past 100,000."  # description 우선 + HTML 제거
    assert doc.body is None  # P5: 뉴스 본문 grounding 불가
    assert doc.lang == "en"
    assert doc.published_at is not None
    assert doc.published_at.tzinfo == timezone.utc
    assert doc.published_at.hour == 9 and doc.published_at.minute == 0

    # description 없으면 snippet으로 폴백.
    doc2 = normalize(items[1])
    assert doc2.summary == "ETH mainnet upgrade goes live."


def test_fetch_sends_token_and_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "marketaux_api_key", "test-token")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.url.params.get("api_token")
        seen["symbols"] = request.url.params.get("symbols")
        return httpx.Response(200, content=_SAMPLE)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        conn = MarketauxConnector(symbols="BTC,ETH", client=client)
        items = list(conn.fetch())

    assert seen["token"] == "test-token"
    assert seen["symbols"] == "BTC,ETH"
    assert [i["uuid"] for i in items] == ["mx-1", "mx-2"]


def test_fetch_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "marketaux_api_key", None)
    with pytest.raises(MarketauxError):
        list(MarketauxConnector().fetch())
