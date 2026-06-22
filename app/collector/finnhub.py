"""Finnhub 크립토 뉴스 커넥터 (STAGE1.5_DESIGN §4 Track A — 크립토 주력 소스).

Finnhub `/news?category=crypto`는 헤드라인+요약+링크를 JSON 리스트로 준다(§5 주력
크립토 소스). 합법 경계(P5): 본문 직접 수집 금지 — 요약까지만(body=None). 무료
티어 60 req/min. parse_news/normalize는 순수 함수(네트워크·DB 없이 테스트 가능),
fetch/upsert만 I/O. 키(finnhub_api_key) 없으면 비활성(FinnhubError).
"""

from __future__ import annotations

import ssl
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import httpx
import truststore
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.collector.base import Connector, NormalizedDoc
from app.config import settings
from app.db import SessionLocal
from app.models import RawDocument, Source

_NEWS_URL = "https://finnhub.io/api/v1/news"
_LEGAL_BASIS = "Finnhub API — 헤드라인+요약+링크만(P5)"


class FinnhubError(RuntimeError):
    """finnhub_api_key 미설정 등 커넥터를 진행할 수 없는 상태."""


def parse_news(payload_json: list[Any]) -> list[dict[str, Any]]:
    """Finnhub /news 응답(아이템 dict 리스트)을 그대로 원시 dict 리스트로 (순수).

    형식: [{"id","headline","summary","url","datetime","source","category","image"}].
    """
    return [item for item in payload_json if isinstance(item, dict)]


def normalize(payload: dict[str, Any]) -> NormalizedDoc:
    """원시 아이템 → 공통 스키마 (순수). datetime은 Unix epoch(초), 0/없으면 None."""
    unix = payload.get("datetime")
    published_at = None
    if unix:
        published_at = datetime.fromtimestamp(unix, tz=timezone.utc)
    return NormalizedDoc(
        source="finnhub",
        external_id=str(payload.get("id")),
        published_at=published_at,
        title=payload.get("headline"),
        summary=payload.get("summary"),
        body=None,  # P5: 뉴스 요약만, 본문 grounding 불가
        url=payload.get("url"),
        lang="en",
        raw_payload=payload,
    )


class FinnhubConnector(Connector):
    def __init__(self, *, category: str = "crypto", client: httpx.Client | None = None) -> None:
        self.category = category
        self.client = client

    def fetch(self) -> Iterable[dict[str, Any]]:
        """Finnhub /news에서 원시 아이템을 yield. 무료 티어 60 req/min 한도.

        키 미설정 시 FinnhubError. client 주입 시 그걸 쓴다(테스트). 미주입 시
        OS 인증서 신뢰(사내 TLS 가로채기 대응) truststore 클라이언트 1회용.
        """
        if not settings.finnhub_api_key:
            raise FinnhubError("finnhub_api_key 미설정 — Finnhub 접근 불가(§5)")
        owns = self.client is None
        if self.client is not None:
            http = self.client
        else:
            ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            http = httpx.Client(timeout=20.0, verify=ctx)
        try:
            resp = http.get(
                _NEWS_URL,
                params={"category": self.category, "token": settings.finnhub_api_key},
            )
            resp.raise_for_status()
            yield from parse_news(resp.json())
        finally:
            if owns:
                http.close()

    def normalize(self, payload: dict[str, Any]) -> NormalizedDoc:
        return normalize(payload)

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
