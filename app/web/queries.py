"""대시보드 읽기 모듈 (STAGE1_DASHBOARD_SPEC). brief_items 추적성 뷰 조립.

프로젝트 I/O 경계 관례(rss.py/citations.py)대로 라우트에서 분리한다. 순수 SELECT만 —
쓰기·커밋 없음(읽기 전용 화면). brief_item + tickers + citations(+raw_documents url/title)를
브리프당으로 그룹핑한다. 티커×인용 카티전 폭발을 피하려 세 쿼리로 나눠 메모리에서 묶는다.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    BriefItem,
    BriefItemTicker,
    Citation,
    DailyDigest,
    DigestSource,
    RawDocument,
)


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


def _asset_classes(tickers: list[TickerView]) -> list[str]:
    """티커들의 market을 자산 분류로 매핑한 정렬된 distinct 리스트.

    CRYPTO→"crypto", 그 외(KR·US)→"stock". 티커 없으면 [](전체 탭에서만 노출).
    한 brief에 자산이 섞이면 둘 다 반환 → 양쪽 탭 모두 노출.
    """
    classes = {"crypto" if t.market == "CRYPTO" else "stock" for t in tickers}
    return sorted(classes)


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
    impact_score: int | None = None  # 임팩트 크기 0~100(랭킹 보드 정렬 키). None=미분석.
    cluster_id: int | None = None  # 그룹(색·모양 인코딩)으로 묶는 클러스터 id.

    @property
    def last_updated(self) -> datetime:
        """이 브리프의 가장 최근 시각: 생성시각과 인용 소스 발행시각 중 최대."""
        times = [self.generated_at]
        times += [c.source_published_at for c in self.citations if c.source_published_at]
        return max(times)

    @property
    def asset_classes(self) -> list[str]:
        """자산 탭 필터용 분류(crypto/stock). 티커 없으면 [](전체 탭에서만 노출)."""
        return _asset_classes(self.tickers)


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
            impact_score=item.impact_score,
            cluster_id=item.cluster_id,
        )
        for item in items
    ]


@dataclass(frozen=True)
class BoardRow:
    """임팩트 랭킹 보드 1행(이벤트 단위). 그룹=클러스터, 색+모양+문자 3중 인코딩."""

    brief_id: int
    group_label: str  # "G1" 등 (날짜 내 클러스터 등장 순서)
    group_shape: str  # ●/▲/■ (색맹 구분용 모양 인코딩)
    group_index: int  # 1..N (색 클래스 g1..gN 선택; 팔레트 크기로 순환 — 모양과 같은 주기)
    impact_score: int
    direction: str | None
    event_type: str | None
    tickers: list[TickerView]

    @property
    def asset_classes(self) -> list[str]:
        """자산 탭 필터용 분류(crypto/stock). 티커 없으면 [](전체 탭에서만 노출)."""
        return _asset_classes(self.tickers)


_GROUP_SHAPES = ["●", "▲", "■", "◆", "★"]


def dates_with_briefs(session: Session) -> set[date]:
    """brief_item이 하나라도 있는 brief_date의 set (날짜 칩 has_data 판정용, 순수 SELECT)."""
    return set(session.execute(select(BriefItem.brief_date).distinct()).scalars())


def rank_board(briefs: Sequence[BriefView]) -> list[BoardRow]:
    """분석된 브리프(status=ok·impact_score 있음)를 임팩트 내림차순 보드 행으로 (순수).

    임팩트 스코어는 이벤트(brief_item)당 1개라 행도 이벤트 단위다 — 티커별 점수는
    데이터에 없으므로 만들지 않는다(zero-fabrication). 그룹 라벨(G1..)은 클러스터가
    보드에 등장하는 순서대로 부여하고, 색+모양을 함께 입혀 색맹도 구분 가능하게 한다.
    """
    scored = sorted(
        (b for b in briefs if b.impact_score is not None and b.status == "ok"),
        key=lambda b: b.impact_score or 0,
        reverse=True,
    )
    group_of: dict[int | None, int] = {}
    rows: list[BoardRow] = []
    for b in scored:
        if b.cluster_id not in group_of:
            group_of[b.cluster_id] = len(group_of) + 1
        gi = group_of[b.cluster_id]
        rows.append(
            BoardRow(
                brief_id=b.id,
                group_label=f"G{gi}",
                group_shape=_GROUP_SHAPES[(gi - 1) % len(_GROUP_SHAPES)],
                group_index=(gi - 1) % len(_GROUP_SHAPES) + 1,
                impact_score=b.impact_score or 0,
                direction=b.direction,
                event_type=b.event_type,
                tickers=b.tickers,
            )
        )
    return rows


def board_asset_counts(board: Sequence[BoardRow]) -> dict[str, int]:
    """탭 버튼 라벨용 자산별 보드 행 수. all=전체, stock/crypto=해당 자산이 링크된 행 수.

    한 행이 두 자산을 모두 링크하면 양쪽에 카운트(탭 양쪽에 노출되므로 일치). 티커
    없는 행은 all에만 포함 — 자산 탭에서 숨겨지는 현 동작과 카운트를 맞춘다.
    """
    counts = {"all": len(board), "stock": 0, "crypto": 0}
    for row in board:
        for cls in row.asset_classes:
            counts[cls] += 1
    return counts


def search_citation_spans(
    session: Session, query_vec: Sequence[float], top_k: int = 8
) -> list[CitationView]:
    """질문 벡터로 **누적 코퍼스 전체**의 인용 span을 코사인 유사도로 검색 (§4 트랙 D2).

    하루치 load_brief와 달리 날짜 필터가 없다 — 전 날짜 citations를 가로질러(cross-date)
    검색한다. 검색 대상은 citations(cited_text) — 이미 zero-fabrication ground truth라
    검색이 경계를 깨지 않는다(§D: 검색은 무엇을 먹일지만 바꾼다). raw_documents에 join해
    임베딩 있는 문서만(embedding IS NOT NULL) 후보로 두고, RawDocument.embedding의
    cosine_distance(HNSW vector_cosine_ops 인덱스)로 가까운 순 top_k를 가져온다.

    같은 (url, cited_text)는 가까운 순서를 유지하며 한 번만 반환(링크 중복 제거).
    """
    rows = session.execute(
        select(Citation, RawDocument.url, RawDocument.title)
        .join(RawDocument, RawDocument.id == Citation.raw_document_id)
        .where(RawDocument.embedding.is_not(None))
        .order_by(RawDocument.embedding.cosine_distance(query_vec))
        .limit(top_k)
    )
    views: list[CitationView] = []
    seen: set[tuple[str | None, str]] = set()
    for cit, url, title in rows:
        key = (url, cit.cited_text)
        if key in seen:
            continue
        seen.add(key)
        views.append(
            CitationView(
                cited_text=cit.cited_text,
                source_published_at=cit.source_published_at,
                url=url,
                title=title,
            )
        )
    return views


def _section_label(section: str) -> str:
    """raw section('macro' | 'sector:<name>')을 한국어 라벨로 휴머나이즈 (§4 트랙 E)."""
    if section == "macro":
        return "거시"
    if section.startswith("sector:"):
        return section[len("sector:") :]
    return section


@dataclass(frozen=True)
class DigestView:
    """일일 다이제스트 섹션 1건 (§7). source_brief_item_ids → 근거 brief_item 역추적."""

    section_label: str
    raw_section: str
    heading: str | None
    body_text: str | None
    status: str
    source_brief_item_ids: list[int]


def load_digest(session: Session, brief_date: date) -> list[DigestView]:
    """해당 brief_date의 일일 다이제스트 섹션을 거시 먼저, 그다음 섹터 순으로 조립 (§7).

    각 섹션의 근거 brief_item id는 digest_sources에서 묶는다. 행이 없으면 빈 리스트.
    """
    macro_first = case((DailyDigest.section == "macro", 0), else_=1)
    digests = (
        session.execute(
            select(DailyDigest)
            .where(DailyDigest.brief_date == brief_date)
            .order_by(macro_first, DailyDigest.section)
        )
        .scalars()
        .all()
    )
    if not digests:
        return []

    ids = [d.id for d in digests]
    sources_by_digest: dict[int, list[int]] = defaultdict(list)
    for digest_id, brief_item_id in session.execute(
        select(DigestSource.digest_id, DigestSource.brief_item_id)
        .where(DigestSource.digest_id.in_(ids))
        .order_by(DigestSource.brief_item_id)
    ):
        sources_by_digest[digest_id].append(brief_item_id)

    return [
        DigestView(
            section_label=_section_label(d.section),
            raw_section=d.section,
            heading=d.heading,
            body_text=d.body_text,
            status=d.status,
            source_brief_item_ids=sources_by_digest[d.id],
        )
        for d in digests
    ]


@dataclass(frozen=True)
class SourceStatus:
    """일일 실행에서 소스 1건의 수집 결과 (§8.6 투명성)."""

    name: str
    status: str
    attempted: int
    error: str | None


@dataclass(frozen=True)
class SourceHealthView:
    """가장 최근 daily_run의 소스 헬스 + 다이제스트 상태 + 실행 시각 (§4 트랙 B / §8.6)."""

    sources: list[SourceStatus]
    digest_status: str
    ran_at: datetime


def load_source_health(session: Session, brief_date: date) -> SourceHealthView | None:
    """해당 brief_date의 가장 최근 daily_run audit_log 1건을 소스 헬스 뷰로 파싱 (§8.6).

    payload->>'brief_date' == brief_date.isoformat()인 행 중 ts 내림차순 최신 1건. 없으면 None.
    """
    row = session.execute(
        select(AuditLog)
        .where(
            AuditLog.action == "daily_run",
            AuditLog.payload.op("->>")("brief_date") == brief_date.isoformat(),
        )
        .order_by(AuditLog.ts.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None

    payload = row.payload or {}
    sources = [
        SourceStatus(
            name=s.get("name", ""),
            status=s.get("status", ""),
            attempted=s.get("attempted", 0),
            error=s.get("error"),
        )
        for s in payload.get("sources", [])
    ]
    return SourceHealthView(
        sources=sources,
        digest_status=payload.get("digest_status", ""),
        ran_at=row.ts,
    )
