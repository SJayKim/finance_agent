"""run_pipeline DB 통합테스트 (§6.2 dedup + §6.3 cluster → brief_items).

단위 테스트(test_dedup)는 near_duplicate_groups 순수 함수를 덮는다. 여기선 DB 단계
배선을 실 Postgres로 덮는다: cluster() 베이스라인이 단독 문서를 1-멤버 클러스터로
만들어 brief_item이 되는지, 재실행이 멱등인지. dictionary={}로 ticker_link는 0건
적재(오프라인 — OpenFIGI 네트워크 미접촉).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.models import BriefItem, Citation, Cluster, RawDocument, Source
from app.pipeline.citations import CitedSpan, ImpactResult, SourceDoc
from app.pipeline.pipeline import analyze_impact, run_pipeline

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


def _grounded_analyzer(docs: Sequence[SourceDoc]) -> ImpactResult | None:
    """가짜 §7 분석기: 첫 멤버 문서를 인용하는 ok 결과를 돌려준다(네트워크 없이 적재 검증)."""
    first = docs[0]
    return ImpactResult(
        analysis_text="impact for " + (first.title or ""),
        citations=[
            CitedSpan(
                raw_document_id=first.raw_document_id,
                cited_text=first.title or "",
                char_start=0,
                char_end=len(first.title or ""),
                source_published_at=first.published_at,
            )
        ],
        event_type="price_move",
        direction="긍정",
        confidence="MED",
        impact_score=88,
    )


def _citation_count(db: sessionmaker) -> int:
    with db() as s:
        return s.execute(select(func.count()).select_from(Citation)).scalar_one()


def test_analyze_impact_fills_brief_items_and_citations(db: sessionmaker) -> None:
    _seed(db)
    run_pipeline(_BRIEF_DATE, dictionary={}, analyzer=_grounded_analyzer)
    with db() as s:
        items = s.execute(select(BriefItem)).scalars().all()
    assert len(items) == 2
    assert all(i.status == "ok" for i in items)
    assert all(i.event_type == "price_move" and i.direction == "긍정" for i in items)
    assert all(i.impact_score == 88 for i in items)
    assert all(i.analysis_text for i in items)
    assert _citation_count(db) == 2  # 클러스터당 인용 1건


def test_analyze_impact_degraded_on_analyzer_failure(db: sessionmaker) -> None:
    _seed(db)
    run_pipeline(_BRIEF_DATE, dictionary={}, analyzer=lambda docs: None)  # API 장애 흉내
    with db() as s:
        items = s.execute(select(BriefItem)).scalars().all()
    assert all(i.status == "degraded" for i in items)
    assert _citation_count(db) == 0


def test_analyze_impact_rerun_skips_ok_items(db: sessionmaker) -> None:
    _seed(db)
    run_pipeline(_BRIEF_DATE, dictionary={}, analyzer=_grounded_analyzer)
    run_pipeline(_BRIEF_DATE, dictionary={}, analyzer=_grounded_analyzer)  # ok는 재분석 안 함
    assert _citation_count(db) == 2  # 중복 인용 적재 없음


# --- 상한·점진 커밋 (2026-07-04 timeout 전량 롤백 회귀 방지) ---


def test_analyze_cap_prioritizes_multisource_and_resumes(db: sessionmaker) -> None:
    """상한=1이면 멤버 수 많은(멀티소스) 클러스터부터 1건만 분석하고, 재실행이 이어서 분석한다."""
    _seed(db)
    calls: list[int] = []  # 호출당 클러스터 소스 문서 수

    def counting_analyzer(docs: Sequence[SourceDoc]) -> ImpactResult | None:
        calls.append(len(docs))
        return _grounded_analyzer(docs)

    run_pipeline(_BRIEF_DATE, dictionary={}, analyzer=counting_analyzer, impact_max_clusters=1)
    assert calls == [2]  # 멤버 2(근접중복 클러스터)가 단독(1)보다 우선
    with db() as s:
        statuses = sorted(s.execute(select(BriefItem.status)).scalars())
    assert statuses == ["empty", "ok"]  # 상한 밖은 손대지 않아 empty 유지

    run_pipeline(_BRIEF_DATE, dictionary={}, analyzer=counting_analyzer, impact_max_clusters=1)
    assert calls == [2, 1]  # 재실행이 남은 empty를 이어서 분석(멱등)
    with db() as s:
        statuses = sorted(s.execute(select(BriefItem.status)).scalars())
    assert statuses == ["ok", "ok"]


def test_skeleton_survives_analyzer_crash(db: sessionmaker) -> None:
    """분석기가 죽어도(timeout 강제 종료 상당) 골격 커밋이 남는다 — 전량 롤백 회귀 방지."""
    _seed(db)

    def crashing_analyzer(docs: Sequence[SourceDoc]) -> ImpactResult | None:
        raise RuntimeError("simulated kill")

    with pytest.raises(RuntimeError):
        run_pipeline(_BRIEF_DATE, dictionary={}, analyzer=crashing_analyzer)
    assert _counts(db) == (2, 2)  # clusters/brief_items(empty)는 커밋돼 있다
    with db() as s:
        statuses = s.execute(select(BriefItem.status)).scalars().all()
    assert all(status == "empty" for status in statuses)


def test_analyze_impact_checkpoint_persists_progress(db: sessionmaker) -> None:
    """checkpoint_every=1: 2건째에서 죽어도 1건째 분석(ok)은 커밋돼 새 세션에서 보인다."""
    _seed(db)
    run_pipeline(_BRIEF_DATE, dictionary={}, analyzer=None)  # 골격만(분석 비활성)
    calls = {"n": 0}

    def flaky_analyzer(docs: Sequence[SourceDoc]) -> ImpactResult | None:
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("simulated kill on second item")
        return _grounded_analyzer(docs)

    with db() as s:
        with pytest.raises(RuntimeError):
            analyze_impact(
                s, _BRIEF_DATE, flaky_analyzer, checkpoint=s.commit, checkpoint_every=1
            )
    with db() as s:
        ok_n = s.execute(
            select(func.count()).select_from(BriefItem).where(BriefItem.status == "ok")
        ).scalar_one()
    assert ok_n == 1
