"""커넥터 공통 패턴 (STAGE1_DESIGN §5): 수집 → normalize → raw_documents 멱등 upsert.

구체 소스(네이버·OpenDART·EDGAR·KRX·CoinGecko·Marketaux·Finnhub·RSS)는 이 계약을
구현한다. 합법 경계(P5): 본문 grounding은 공시뿐, 뉴스/RSS는 헤드라인+요약+링크까지.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class NormalizedDoc:
    """§5 공통 정규화 필드."""

    source: str
    external_id: str
    published_at: datetime | None
    title: str | None
    summary: str | None
    body: str | None  # 합법 수집 가능할 때만 (공시)
    url: str | None
    lang: str | None
    raw_payload: dict[str, Any]


class Connector(ABC):
    """모든 소스 커넥터의 계약."""

    @abstractmethod
    def fetch(self) -> Iterable[dict[str, Any]]:
        """소스에서 원시 페이로드를 가져온다."""

    @abstractmethod
    def normalize(self, payload: dict[str, Any]) -> NormalizedDoc:
        """원시 페이로드를 공통 스키마로 정규화한다."""

    @abstractmethod
    def upsert(self, doc: NormalizedDoc) -> None:
        """raw_documents에 멱등 upsert (source_id, external_id 기준)."""
