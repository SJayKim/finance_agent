"""대시보드 읽기 모듈 (STAGE1_DASHBOARD_SPEC). brief_items 추적성 뷰 조립.

프로젝트 I/O 경계 관례(rss.py/citations.py)대로 라우트에서 분리한다. 순수 SELECT만 —
쓰기·커밋 없음(읽기 전용 화면). brief_item + tickers + citations(+raw_documents url/title)를
브리프당으로 그룹핑한다. 티커×인용 카티전 폭발을 피하려 세 쿼리로 나눠 메모리에서 묶는다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BriefItem, BriefItemTicker, Citation, RawDocument


@dataclass(frozen=True)
class CitationView:
    """인용 1건 + 역참조한 원문 링크(없으면 None → '원문 링크 없음')."""

    cited_text: str
    source_published_at: datetime | None
    url: str | None
    title: str | None


@dataclass(frozen=True)
class TickerView:
    """영향 종목 1건. is_candidate면 사전 중의적 후보(§6.4) → '후보' 표기."""

    ticker: str
    market: str
    is_candidate: bool


@dataclass(frozen=True)
class BriefView:
    """brief_item 1건의 추적성 뷰: 항목 메타 + 종목 + 인용 근거."""

    id: int
    event_type: str | None
    direction: str | None
    confidence: str | None
    analysis_text: str | None
    status: str
    generated_at: datetime
    tickers: list[TickerView]
    citations: list[CitationView]

    @property
    def last_updated(self) -> datetime:
        """이 브리프의 가장 최근 시각: 생성시각과 인용 소스 발행시각 중 최대."""
        times = [self.generated_at]
        times += [c.source_published_at for c in self.citations if c.source_published_at]
        return max(times)


def load_brief(session: Session, brief_date: date) -> list[BriefView]:
    """해당 brief_date의 brief_items를 추적성 뷰로 조립 (id 오름차순).

    brief 0건이면 빈 리스트. 인용은 raw_documents에 outer join — 원문이 사라져도
    인용 텍스트는 남으므로 url/title이 None일 수 있다(템플릿이 '원문 링크 없음' 처리).
    """
    items = (
        session.execute(
            select(BriefItem).where(BriefItem.brief_date == brief_date).order_by(BriefItem.id)
        )
        .scalars()
        .all()
    )
    if not items:
        return []

    ids = [item.id for item in items]

    tickers_by_item: dict[int, list[TickerView]] = defaultdict(list)
    for row in session.execute(
        select(BriefItemTicker)
        .where(BriefItemTicker.brief_item_id.in_(ids))
        .order_by(BriefItemTicker.ticker, BriefItemTicker.market)
    ).scalars():
        tickers_by_item[row.brief_item_id].append(
            TickerView(ticker=row.ticker, market=row.market, is_candidate=row.is_candidate)
        )

    citations_by_item: dict[int, list[CitationView]] = defaultdict(list)
    for cit, url, title in session.execute(
        select(Citation, RawDocument.url, RawDocument.title)
        .outerjoin(RawDocument, RawDocument.id == Citation.raw_document_id)
        .where(Citation.brief_item_id.in_(ids))
        .order_by(Citation.id)
    ):
        citations_by_item[cit.brief_item_id].append(
            CitationView(
                cited_text=cit.cited_text,
                source_published_at=cit.source_published_at,
                url=url,
                title=title,
            )
        )

    return [
        BriefView(
            id=item.id,
            event_type=item.event_type,
            direction=item.direction,
            confidence=item.confidence,
            analysis_text=item.analysis_text,
            status=item.status,
            generated_at=item.generated_at,
            tickers=tickers_by_item[item.id],
            citations=citations_by_item[item.id],
        )
        for item in items
    ]
