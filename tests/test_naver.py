import json
from datetime import timezone

import httpx
import pytest

from app.collector.naver import NaverError, NaverNewsConnector, parse_news
from app.config import settings

# title/description은 <b> 하이라이트 태그 + HTML 엔티티로 온다(실제 응답과 동일).
# item 0: originallink 있음. item 1: originallink 빈 문자열 → link로 폴백.
_SAMPLE = json.dumps(
    {
        "items": [
            {
                "title": "<b>삼성전자</b> 신고가 &amp; 반등",
                "originallink": "https://news.example.com/a",
                "link": "https://n.news.naver.com/a",
                "description": "&lt;b&gt;코스피&lt;/b&gt; 강세 속 반등.",
                "pubDate": "Mon, 22 Jun 2026 09:00:00 +0900",
            },
            {
                "title": "<b>금리</b> 동결 전망",
                "originallink": "",
                "link": "https://n.news.naver.com/b",
                "description": "한은 금리 동결 가능성.",
                "pubDate": "not-a-date",
            },
        ]
    }
).encode("utf-8")


def test_parse_news_extracts_items() -> None:
    items = parse_news(json.loads(_SAMPLE))
    assert len(items) == 2
    assert items[0]["external_id"] == "https://news.example.com/a"


def test_normalize_strips_html_and_parses_pubdate_utc() -> None:
    conn = NaverNewsConnector(["삼성전자"])
    doc = conn.normalize(parse_news(json.loads(_SAMPLE))[0])
    assert "<b>" not in (doc.title or "") and "&amp;" not in (doc.title or "")
    assert "<b>" not in (doc.summary or "") and "&lt;" not in (doc.summary or "")
    assert doc.title == "삼성전자 신고가 & 반등"
    assert doc.summary == "코스피 강세 속 반등."
    assert doc.body is None  # P5: 네이버 본문 grounding 불가
    assert doc.lang == "ko"
    assert doc.published_at is not None
    assert doc.published_at.tzinfo == timezone.utc
    assert doc.published_at.hour == 0  # +0900 09:00 → UTC 00:00


def test_normalize_external_id_falls_back_to_link() -> None:
    doc = NaverNewsConnector(["금리"]).normalize(parse_news(json.loads(_SAMPLE))[1])
    assert doc.external_id == "https://n.news.naver.com/b"
    assert doc.published_at is None  # 잘못된 pubDate → None


def test_fetch_sends_auth_headers_and_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "naver_client_id", "cid")
    monkeypatch.setattr(settings, "naver_client_secret", "csecret")
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["id"] = request.headers.get("X-Naver-Client-Id")
        seen["secret"] = request.headers.get("X-Naver-Client-Secret")
        return httpx.Response(200, content=_SAMPLE)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        conn = NaverNewsConnector(["삼성전자"], client=client)
        items = list(conn.fetch())

    assert seen["id"] == "cid"
    assert seen["secret"] == "csecret"
    assert len(items) == 2
    assert items[0]["query"] == "삼성전자"  # 추적성 태그


def test_fetch_missing_keys_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "naver_client_id", None)
    monkeypatch.setattr(settings, "naver_client_secret", None)
    with pytest.raises(NaverError):
        list(NaverNewsConnector(["코스피"]).fetch())
