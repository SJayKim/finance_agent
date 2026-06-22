"""네이버 검색 오픈API 뉴스 커넥터 (STAGE1.5_DESIGN §4 Track A — KR 뉴스).

GET /v1/search/news.json. 합법 경계(P5): 네이버는 헤드라인+요약+링크만 주므로
본문 grounding 불가(body=None). 인증은 헤더 2종(Client-Id/Secret) — config에 이미
있음(키 없으면 fetch가 NaverError로 비활성). parse_news/normalize는 순수 함수
(네트워크·DB 없이 테스트 가능), fetch/upsert만 I/O. rss.py 레퍼런스.
"""

from __future__ import annotations

import html
import re
import ssl
from collections.abc import Iterable
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
import truststore
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.collector.base import Connector, NormalizedDoc
from app.config import settings
from app.db import SessionLocal
from app.models import RawDocument, Source

_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"
_LEGAL_BASIS = "Naver Search OpenAPI; 헤드라인+요약+링크만(P5)"
_TAG = re.compile(r"<[^>]+>")

# §4 Track A: KR 시장 키워드 기본 세트. 프로덕션은 coverage/security_aliases에서
# 쿼리를 도출해야 한다(쿼리는 커버리지 종목/섹터 키워드+별칭).
DEFAULT_QUERIES: list[str] = ["코스피", "반도체", "금리", "환율", "삼성전자"]


class NaverError(RuntimeError):
    """네이버 인증 키(Client-Id/Secret) 미설정 — 커넥터 비활성."""


def _strip_html(value: str | None) -> str | None:
    if value is None:
        return None
    return _TAG.sub("", html.unescape(value)).strip() or None


def parse_news(payload_json: dict[str, Any]) -> list[dict[str, Any]]:
    """news.json 응답 dict → item 원시 dict 리스트 (순수). 네트워크 없음.

    external_id = originallink 우선, 없으면 link.
    """
    items: list[dict[str, Any]] = []
    for item in payload_json.get("items", []):
        original = item.get("originallink") or None
        link = item.get("link") or None
        items.append(
            {
                "external_id": original or link,
                "title": item.get("title"),
                "description": item.get("description"),
                "originallink": original,
                "link": link,
                "pubDate": item.get("pubDate"),
            }
        )
    return items


class NaverNewsConnector(Connector):
    def __init__(
        self,
        queries: list[str],
        *,
        display: int = 100,
        client: httpx.Client | None = None,
    ) -> None:
        self.queries = queries
        self.display = display
        self._client = client

    def fetch(self) -> Iterable[dict[str, Any]]:
        # 쿼터 노트(§5): 일 호출 한도 = display × len(queries) 가 네이버 일 한도 내여야 함.
        if not settings.naver_client_id or not settings.naver_client_secret:
            raise NaverError(
                "naver_client_id/naver_client_secret 미설정 — 네이버 검색 API에 키 2개 필수(§4)"
            )
        headers = {
            "X-Naver-Client-Id": settings.naver_client_id,
            "X-Naver-Client-Secret": settings.naver_client_secret,
        }
        owns = self._client is None
        # OS 인증서 저장소 신뢰(사내 TLS 가로채기 대응; rss.py와 동일 패턴).
        http = self._client or httpx.Client(
            timeout=20.0,
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        )
        try:
            for query in self.queries:
                params: dict[str, str | int] = {
                    "query": query,
                    "display": self.display,
                    "start": 1,
                    "sort": "date",
                }
                resp = http.get(_NEWS_URL, headers=headers, params=params)
                resp.raise_for_status()
                for item in parse_news(resp.json()):
                    item["query"] = query  # 추적성: 어떤 키워드에서 왔는지
                    yield item
        finally:
            if owns:
                http.close()

    def normalize(self, payload: dict[str, Any]) -> NormalizedDoc:
        pub_raw = payload.get("pubDate")
        published_at = None
        if pub_raw:
            try:
                published_at = parsedate_to_datetime(pub_raw).astimezone(timezone.utc)
            except (TypeError, ValueError):
                published_at = None
        return NormalizedDoc(
            source="naver_news",
            external_id=payload["external_id"],
            published_at=published_at,
            title=_strip_html(payload.get("title")),
            summary=_strip_html(payload.get("description")),
            body=None,  # P5: 네이버는 요약만 — 본문 grounding 불가
            url=payload.get("link"),
            lang="ko",
            raw_payload=payload,
        )

    def upsert(self, doc: NormalizedDoc) -> None:
        """raw_documents 멱등 upsert. (source_id, external_id) 충돌 시 무시."""
        with SessionLocal() as session:
            source = session.scalar(select(Source).where(Source.name == doc.source))
            if source is None:
                source = Source(name=doc.source, kind="news", legal_basis=_LEGAL_BASIS)
                session.add(source)
                session.flush()
            stmt = (
                insert(RawDocument)
                .values(
                    source_id=source.id,
                    external_id=doc.external_id,
                    published_at=doc.published_at,
                    lang=doc.lang,
                    title=doc.title,
                    summary=doc.summary,
                    body=doc.body,
                    url=doc.url,
                    raw_payload=doc.raw_payload,
                )
                .on_conflict_do_nothing(constraint="uq_raw_documents_source_external")
            )
            session.execute(stmt)
            session.commit()
