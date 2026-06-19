"""고정 파이프라인 단계 (STAGE1_DESIGN §6).

normalize → dedup(SimHash→임베딩 cosine) → cluster → ticker-link(OpenFIGI+사전)
→ event-classify → 영향도 생성(2-패스 Citations, §7).

단계 간 상태는 DB로 흐른다(§3·§8: Postgres가 단일 상태 저장소). run_pipeline은
구현된 단계만 명시 호출하고, 나머지는 구현될 때 한 줄씩 추가한다.
현재: dedup → 영향도 골격(brief_items) → ticker-link 배선까지.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import BriefItem, BriefItemTicker, Cluster, ClusterMember, RawDocument
from app.pipeline.dedup import near_duplicate_groups
from app.pipeline.ticker_link import openfigi_normalizer, resolve


_PIPELINE_LOCK_KEY = 1_958_374_620  # arbitrary stable bigint for pg_try_advisory_lock


class PipelineAlreadyRunning(RuntimeError):
    """run_pipeline 동시 실행 방지 가드 위반."""


def normalize() -> None:
    raise NotImplementedError


def _freshness_cutoff(brief_date: date, hours: int) -> datetime:
    """brief_date 종일(UTC 다음날 00:00)에서 hours를 뺀 신선도 컷오프 (§5.7)."""
    end_of_day = datetime(brief_date.year, brief_date.month, brief_date.day, tzinfo=timezone.utc) + timedelta(days=1)
    return end_of_day - timedelta(hours=hours)


def _candidate_docs(session: Session, cutoff: datetime) -> list[tuple[int, str]]:
    """아직 어떤 클러스터에도 안 들어간, 신선도 윈도우 내 제목 있는 raw_documents (멱등 재실행 대비).

    published_at IS NULL인 문서는 신선도를 알 수 없으므로 포함(배제 금지).
    """
    clustered = select(ClusterMember.raw_document_id)
    rows = session.execute(
        select(RawDocument.id, RawDocument.title).where(
            RawDocument.id.not_in(clustered),
            (RawDocument.published_at >= cutoff) | RawDocument.published_at.is_(None),
        )
    ).all()
    return [(doc_id, title) for doc_id, title in rows if title is not None]


def dedup(session: Session, brief_date: date, freshness_window_hours: int) -> None:
    """dedup 1차: 제목 SimHash 근접중복 그룹을 clusters/cluster_members로 적재 (§6.2).

    크기 ≥2 그룹만 클러스터가 된다(단독 문서는 cluster 단계(§6.3) 몫). 이미 클러스터에
    속한 문서는 후보에서 빠져 재실행이 중복 적재하지 않는다. 커밋은 호출자(run_pipeline).
    신선도 컷오프(§5.7): published_at >= _freshness_cutoff(brief_date, freshness_window_hours)
    또는 published_at IS NULL인 문서만 후보로 받는다.
    """
    cutoff = _freshness_cutoff(brief_date, freshness_window_hours)
    for group in near_duplicate_groups(_candidate_docs(session, cutoff)):
        cluster_row = Cluster(brief_date=brief_date, representative_doc_id=min(group))
        session.add(cluster_row)
        session.flush()  # cluster_row.id 확보 후 멤버 적재
        session.add_all(
            ClusterMember(cluster_id=cluster_row.id, raw_document_id=doc_id) for doc_id in group
        )


def cluster() -> None:
    raise NotImplementedError


def _brief_items_without_tickers(session: Session, brief_date: date) -> list[BriefItem]:
    """이 brief_date의 brief_item 중 아직 티커가 안 붙은 것 (멱등 재실행 대비)."""
    linked = select(BriefItemTicker.brief_item_id)
    rows = session.execute(
        select(BriefItem).where(BriefItem.brief_date == brief_date, BriefItem.id.not_in(linked))
    ).scalars()
    return list(rows)


def _representative_title(session: Session, cluster_id: int) -> str | None:
    return session.execute(
        select(RawDocument.title)
        .join(Cluster, Cluster.representative_doc_id == RawDocument.id)
        .where(Cluster.id == cluster_id)
    ).scalar_one_or_none()


def ticker_link(
    session: Session,
    brief_date: date,
    dictionary: Mapping[str, list[tuple[str, str]]],
    normalizer: Callable[[str, str], str | None] | None = None,
) -> None:
    """ticker-link 배선 (§6.4): brief_item 대표문서 제목 → brief_item_tickers.

    순수 resolve()로 사전 별칭을 찾아 적재한다. link_precision은 §6.4 실측 전이라
    NULL(게이트 측정은 후속 작업). is_candidate는 resolve의 판단을 그대로 보존.
    사전이 비면(기본 빈 dict) 아무것도 적재하지 않는다 — 유니버스 하드코딩 금지(§2).
    """
    for item in _brief_items_without_tickers(session, brief_date):
        if item.cluster_id is None:
            continue
        title = _representative_title(session, item.cluster_id)
        if title is None:
            continue
        for link in resolve(title, dictionary, normalizer):
            session.add(
                BriefItemTicker(
                    brief_item_id=item.id,
                    ticker=link.ticker,
                    market=link.market,
                    is_candidate=link.is_candidate,
                )
            )


def event_classify() -> None:
    raise NotImplementedError


def _clusters_without_brief_item(session: Session, brief_date: date) -> list[Cluster]:
    """이 brief_date의 클러스터 중 아직 brief_item이 없는 것 (멱등 재실행 대비)."""
    has_item = select(BriefItem.cluster_id).where(BriefItem.cluster_id.is_not(None))
    rows = session.execute(
        select(Cluster).where(Cluster.brief_date == brief_date, Cluster.id.not_in(has_item))
    ).scalars()
    return list(rows)


def generate_impact(session: Session, brief_date: date) -> None:
    """영향도 생성 골격 (§6.6/§7): 클러스터 → brief_items.

    §7 2-패스 Citations 분석은 미구현이라 event_type·direction·confidence·
    analysis_text는 NULL로 두고 status=empty로 정직하게 표기한다(§10 null-evidence:
    근거 텍스트를 환각으로 채우지 않는다). 클러스터당 brief_item 1건, 멱등. ticker_link가
    이 brief_item을 읽어 티커를 붙이므로 끝에서 flush해 id를 확정한다.
    """
    for cluster_row in _clusters_without_brief_item(session, brief_date):
        session.add(BriefItem(brief_date=brief_date, cluster_id=cluster_row.id, status="empty"))
    session.flush()


def run_pipeline(
    brief_date: date,
    dictionary: Mapping[str, list[tuple[str, str]]] | None = None,
    freshness_window_hours: int = settings.freshness_window_hours,
) -> None:
    """일간 브리프 파이프라인 1회 실행. 현재: dedup → generate_impact(골격) → ticker_link.

    §6 설계 순서는 ticker-link → ... → 영향도생성이나, brief_item_tickers가 brief_items
    FK라 brief_items를 먼저 만들어야 한다 → generate_impact를 ticker_link보다 앞에 둔다.
    cluster·event_classify·§7 Citations 분석은 구현되는 대로 순서대로 추가한다.
    dictionary 미주입 시 빈 사전(링크 0건) — 유니버스 하드코딩 금지(§2).
    """
    with SessionLocal() as session:
        acquired = session.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": _PIPELINE_LOCK_KEY}
        ).scalar()
        if not acquired:
            raise PipelineAlreadyRunning(f"run_pipeline already running (lock {_PIPELINE_LOCK_KEY})")
        try:
            dedup(session, brief_date, freshness_window_hours)
            generate_impact(session, brief_date)
            ticker_link(session, brief_date, dictionary or {}, openfigi_normalizer)
            session.commit()
        finally:
            session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _PIPELINE_LOCK_KEY})
