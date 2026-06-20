"""run_pipeline DB 통합테스트 (§6.2 dedup + §6.3 cluster → brief_items).

단위 테스트(test_dedup)는 near_duplicate_groups 순수 함수를 덮는다. 여기선 DB 단계
배선을 실 Postgres로 덮는다: cluster() 베이스라인이 단독 문서를 1-멤버 클러스터로
만들어 brief_item이 되는지, 재실행이 멱등인지. dictionary={}로 ticker_link는 0건
적재(오프라인 — OpenFIGI 네트워크 미접촉).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.models import BriefItem, Cluster, RawDocument, Source
from app.pipeline.pipeline import run_pipeline

_BRIEF_DATE = date(2026, 6, 20)
_IN_WINDOW = datetime(2026, 6, 20, 12, tzinfo=timezone.utc)  # 신선도 윈도우(24h) 내


def _seed(db: sessionmaker) -> None:
    """근접중복 2건 + 고유 1건 적재. dedup이 2건을 묶고 cluster가 1건을 단독 클러스터로."""
    with db() as s:
        src = Source(name="test-src", kind="news")
        s.add(src)
        s.flush()
        s.add_all(
            [
                RawDocument(
                    source_id=src.id,
                    external_id="a",
                    title="Bitcoin tops $100K",
                    published_at=_IN_WINDOW,
                ),
                RawDocument(
                    source_id=src.id,
                    external_id="b",
                    title="BITCOIN TOPS $100K!!!",
                    published_at=_IN_WINDOW,
                ),
                RawDocument(
                    source_id=src.id,
                    external_id="c",
                    title="Ethereum upgrade goes live on mainnet",
                    published_at=_IN_WINDOW,
                ),
            ]
        )
        s.commit()


def _counts(db: sessionmaker) -> tuple[int, int]:
    with db() as s:
        clusters = s.execute(select(func.count()).select_from(Cluster)).scalar_one()
        items = s.execute(select(func.count()).select_from(BriefItem)).scalar_one()
    return clusters, items


def test_singletons_and_duplicates_become_brief_items(db: sessionmaker) -> None:
    _seed(db)
    run_pipeline(_BRIEF_DATE, dictionary={})
    # dedup: 근접중복 1쌍 → 클러스터 1 / cluster: 고유 1건 → 클러스터 1. 각 클러스터당 brief_item 1건.
    assert _counts(db) == (2, 2)


def test_rerun_is_idempotent(db: sessionmaker) -> None:
    _seed(db)
    run_pipeline(_BRIEF_DATE, dictionary={})
    run_pipeline(_BRIEF_DATE, dictionary={})  # 후보 제외 로직이 중복 적재를 막아야 한다
    assert _counts(db) == (2, 2)
