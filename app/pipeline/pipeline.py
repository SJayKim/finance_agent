"""고정 파이프라인 단계 (STAGE1_DESIGN §6).

normalize → dedup(SimHash→임베딩 cosine) → cluster → ticker-link(OpenFIGI+사전)
→ event-classify → 영향도 생성(2-패스 Citations, §7).

단계 간 상태는 DB로 흐른다(§3·§8: Postgres가 단일 상태 저장소). run_pipeline은
구현된 단계만 명시 호출하고, 나머지는 구현될 때 한 줄씩 추가한다. 현재: dedup 1차까지.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Cluster, ClusterMember, RawDocument
from app.pipeline.dedup import near_duplicate_groups


def normalize() -> None:
    raise NotImplementedError


def _candidate_docs(session: Session) -> list[tuple[int, str]]:
    """아직 어떤 클러스터에도 안 들어간, 제목 있는 raw_documents (멱등 재실행 대비)."""
    clustered = select(ClusterMember.raw_document_id)
    rows = session.execute(
        select(RawDocument.id, RawDocument.title).where(RawDocument.id.not_in(clustered))
    ).all()
    return [(doc_id, title) for doc_id, title in rows if title is not None]


def dedup(session: Session, brief_date: date) -> None:
    """dedup 1차: 제목 SimHash 근접중복 그룹을 clusters/cluster_members로 적재 (§6.2).

    크기 ≥2 그룹만 클러스터가 된다(단독 문서는 cluster 단계(§6.3) 몫). 이미 클러스터에
    속한 문서는 후보에서 빠져 재실행이 중복 적재하지 않는다. 커밋은 호출자(run_pipeline).

    한계(TODO §5.7): 후보를 날짜로 스코프하지 않는다. brief_date는 클러스터 실행일
    도장일 뿐이라, 누적된 옛 문서가 새 근접중복과 묶이면 오늘 날짜로 찍힐 수 있다.
    published_at 신선도 윈도우(config freshness_window_hours) 필터는 §5.7 컷오프
    기준시각·null published_at 처리가 확정되면 _candidate_docs에 추가한다.
    """
    for group in near_duplicate_groups(_candidate_docs(session)):
        cluster_row = Cluster(brief_date=brief_date, representative_doc_id=min(group))
        session.add(cluster_row)
        session.flush()  # cluster_row.id 확보 후 멤버 적재
        session.add_all(
            ClusterMember(cluster_id=cluster_row.id, raw_document_id=doc_id) for doc_id in group
        )


def cluster() -> None:
    raise NotImplementedError


def ticker_link() -> None:
    raise NotImplementedError


def event_classify() -> None:
    raise NotImplementedError


def generate_impact() -> None:
    raise NotImplementedError


def run_pipeline(brief_date: date) -> None:
    """일간 브리프 파이프라인 1회 실행. 현재 구현: dedup 1차까지.

    이후 단계는 구현되는 대로 이 함수에 순서대로 추가한다(§6):
    cluster → ticker_link → event_classify → generate_impact.
    """
    with SessionLocal() as session:
        dedup(session, brief_date)
        session.commit()
