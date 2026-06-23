"""뉴스 RSS 커넥터 (STAGE1_DESIGN §5.8 RSS 티어 + STAGE1.5 §4 Track A).

크립토(CoinTelegraph·CoinDesk·Decrypt) · KR 경제지(한경·매경) · 글로벌 매크로
(연준·ECB·로이터) 퍼블리셔 신디케이션 피드. 합법 경계(P5): 본문 직접 크롤링
금지 — 피드가 주는 헤드라인+요약+링크까지만(body=None). 키 불필요.
parse_feed/normalize는 순수 함수(네트워크·DB 없이 테스트 가능), fetch/upsert만 I/O.
"""

from __future__ import annotations

import html
import logging
import re
import ssl
from collections.abc import Iterable
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree as ET

import httpx
import truststore
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.collector.base import Connector, NormalizedDoc
from app.db import SessionLocal
from app.models import RawDocument, Source

# §5.8 RSS 티어 + STAGE1.5 §4 Track A: source 이름 → {url, lang}.
DEFAULT_FEEDS: dict[str, dict[str, str]] = {
    # 크립토 (en): §5.8 3종 퍼블리셔
    "cointelegraph": {"url": "https://cointelegraph.com/rss", "lang": "en"},
    "coindesk": {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "lang": "en"},
    "decrypt": {"url": "https://decrypt.co/feed", "lang": "en"},
    # KR 경제지 (ko): 한국경제·매일경제 퍼블릭 RSS
    "hankyung": {"url": "https://www.hankyung.com/feed/economy", "lang": "ko"},
    "maeil": {"url": "https://www.mk.co.kr/rss/30100041/", "lang": "ko"},  # 매경 경제
    # 글로벌 매크로 (en): 연준·ECB·로이터
    "federalreserve": {"url": "https://www.federalreserve.gov/feeds/press_all.xml", "lang": "en"},
    "ecb": {"url": "https://www.ecb.europa.eu/rss/press.html", "lang": "en"},
    # 로이터 퍼블릭 RSS는 불안정 — 동작 안 하면 조정 필요.
    "reuters": {"url": "https://feeds.reuters.com/reuters/businessNews", "lang": "en"},
}

_TAG = re.compile(r"<[^>]+>")
_LEGAL_BASIS = "publisher RSS syndication; headline+summary+link only (P5)"
# 일부 퍼블리셔(매경 등)는 비-브라우저 UA를 403으로 막는다 → 브라우저 UA 명시.
_USER_AGENT = "Mozilla/5.0 (compatible; finance-agent/1.0; +RSS reader)"

logger = logging.getLogger(__name__)


def _text(item: ET.Element, tag: str) -> str | None:
    el = item.find(tag)
    return el.text if el is not None else None


def _strip_html(value: str | None) -> str | None:
    if value is None:
        return None
    return html.unescape(_TAG.sub("", value)).strip() or None


def parse_feed(source: str, lang: str, xml_bytes: bytes) -> list[dict[str, Any]]:
    """RSS 2.0 XML → item 원시 dict 리스트 (순수). external_id = guid 우선, 없으면 link."""
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.iter("item"):
        link = _text(item, "link")
        guid = _text(item, "guid")
        items.append(
            {
                "source": source,
                "lang": lang,
                "external_id": guid or link,
                "title": _text(item, "title"),
                "description": _text(item, "description"),
                "link": link,
                "pubDate": _text(item, "pubDate"),
            }
        )
    return items


class RssConnector(Connector):
    def __init__(
        self,
        feeds: dict[str, dict[str, str]] | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.feeds = feeds if feeds is not None else DEFAULT_FEEDS
        self._client = client

    def _make_client(self) -> httpx.Client:
        # OS 인증서 저장소 신뢰 (사내 TLS 가로채기 대응; uv --system-certs의 httpx판).
        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        return httpx.Client(
            timeout=20.0, follow_redirects=True, verify=ctx, headers={"User-Agent": _USER_AGENT}
        )

    def fetch(self) -> Iterable[dict[str, Any]]:
        # 피드별 격리: 한 피드 실패(403·타임아웃·깨진 XML)가 나머지 피드 수집을 막지
        # 않는다. 실패는 로깅하고 다음 피드로 넘어간다 — 매경(mk.co.kr) 한 곳 403이 RSS
        # 전체를 죽이거나 뒤 순번(federalreserve/ecb/reuters)을 건너뛰게 하던 회귀를 막는다.
        owns = self._client is None
        http = self._client or self._make_client()
        try:
            for source, meta in self.feeds.items():
                try:
                    resp = http.get(meta["url"])
                    resp.raise_for_status()
                    items = parse_feed(source, meta["lang"], resp.content)
                except (httpx.HTTPError, ET.ParseError) as exc:
                    logger.warning("rss feed failed: %s: %s", source, exc)
                    continue
                yield from items
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
            source=payload["source"],
            external_id=payload["external_id"],
            published_at=published_at,
            title=_strip_html(payload.get("title")),
            summary=_strip_html(payload.get("description")),
            body=None,  # P5: RSS는 본문 grounding 불가
            url=payload.get("link"),
            lang=payload.get("lang", "en"),  # 피드별 lang (KR=ko, 글로벌 매크로=en)
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
