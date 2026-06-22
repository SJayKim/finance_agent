"""Marketaux 코인 뉴스 커넥터 (STAGE1.5_DESIGN §4 Track A).

엔티티·감성 태깅이 붙은 크립토 뉴스. 합법 경계(P5): 본문 직접 크롤링 금지 —
API가 주는 헤드라인+요약(description/snippet)+링크까지만(body=None). API 키 필요.
parse_news/normalize는 순수 함수(네트워크·DB 없이 테스트 가능), fetch/upsert만 I/O.
"""

from __future__ import annotations

import html
import re
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

_ENDPOINT = "https://api.marketaux.com/v1/news/all"
_TAG = re.compile(r"<[^>]+>")
_LEGAL_BASIS = "Marketaux API — 헤드라인+요약+링크만(P5)"


class MarketauxError(RuntimeError):
    """marketaux_api_key 미설정 등 Marketaux 호출 불가 상태."""


def _strip_html(value: str | None) -> str | None:
    if value is None:
        return None
    return _TAG.sub("", html.unescape(value)).strip() or None


def parse_news(payload_json: dict[str, Any]) -> list[dict[str, Any]]:
    """Marketaux /v1/news/all 응답 → 기사 원시 dict 리스트 (순수). data[] 항목 그대로."""
    return list(payload_json.get("data") or [])


def normalize(payload: dict[str, Any]) -> NormalizedDoc:
    """기사 원시 dict → NormalizedDoc (순수). published_at ISO8601 → UTC-aware, 실패 시 None."""
    pub_raw = payload.get("published_at")
    published_at = None
    if pub_raw:
        try:
            published_at = datetime.fromisoformat(pub_raw).astimezone(timezone.utc)
        except (TypeError, ValueError):
            published_at = None
    summary = payload.get("description") or payload.get("snippet")
    return NormalizedDoc(
        source="marketaux",
        external_id=payload["uuid"],
        published_at=published_at,
        title=_strip_html(payload.get("title")),
        summary=_strip_html(summary),
        body=None,  # P5: 뉴스는 본문 grounding 불가
        url=payload.get("url"),
        lang="en",
        raw_payload=payload,
    )


class MarketauxConnector(Connector):
    def __init__(
        self,
        *,
        symbols: str = "BTC,ETH,SOL,XRP",  # 기본 크립토 유니버스(좁게); .env 없이 동작
        limit: int = 100,
        client: httpx.Client | None = None,
    ) -> None:
        self.symbols = symbols
        self.limit = limit
        self.client = client

    def fetch(self) -> Iterable[dict[str, Any]]:
        # 무료 티어 쿼터: 100 req/day. limit는 호출당 기사 수(요청 1회면 1건 소진).
        if not settings.marketaux_api_key:
            raise MarketauxError("marketaux_api_key 미설정 — Marketaux 접근에 키 필수(§5)")
        owns = self.client is None
        if self.client is not None:
            http = self.client
        else:
            # OS 인증서 저장소 신뢰(사내 TLS 가로채기 대응; rss.py와 동일 패턴).
            ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            http = httpx.Client(timeout=20.0, verify=ctx)
        params: dict[str, str | int] = {
            "api_token": settings.marketaux_api_key,
            "filter_entities": "true",
            "language": "en",
            "symbols": self.symbols,
            "limit": self.limit,
        }
        try:
            resp = http.get(_ENDPOINT, params=params)
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
