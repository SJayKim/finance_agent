"""run_daily DB 통합테스트 (§4 트랙 B: 소스 격리 + audit_log + 빈날 무크래시 + 동시성 가드).

오프라인: 가짜 Connector(네트워크 없음)와 embedder/digester/analyzer=None(또는 가짜
digester)만 쓴다 — 실 모델·실 Anthropic·외부 API 미접촉. _GoodConnector는 raw_documents를
실제로 적재해 run_pipeline이 brief_item을 만들 재료를 준다. _FailingConnector.fetch()는
예외를 던져 소스 격리를 검증한다.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from app.collector.base import Connector, NormalizedDoc
from app.db import SessionLocal
from app.models import AuditLog, BriefItem, DailyDigest, RawDocument, Source
from app.runner import (
    DailyRunAlreadyRunning,
    SourceResult,
    _DAILY_LOCK_KEY,
    run_daily,
)

_BRIEF_DATE = date(2026, 6, 20)
_IN_WINDOW = datetime(2026, 6, 20, 12, tzinfo=timezone.utc)  # 신선도 윈도우(24h) 내


class _GoodConnector(Connector):
    """제목 있는 raw_documents 2건을 멱등 적재하는 가짜 커넥터(네트워크 없음)."""

    def __init__(self, source: str = "fake-good", count: int = 2) -> None:
        self.source = source
        self.count = count

    def fetch(self) -> Iterable[dict[str, Any]]:
        for i in range(self.count):
            yield {"external_id": f"{self.source}-{i}", "title": f"Fake headline {i}"}

    def normalize(self, payload: dict[str, Any]) -> NormalizedDoc:
        return NormalizedDoc(
            source=self.source,
            external_id=payload["external_id"],
            published_at=_IN_WINDOW,
            title=payload["title"],
            summary=None,
            body=None,
            url=None,
            lang="en",
            raw_payload=payload,
        )

    def upsert(self, doc: NormalizedDoc) -> None:
        with SessionLocal() as session:
            source = session.scalar(select(Source).where(Source.name == doc.source))
            if source is None:
                source = Source(name=doc.source, kind="news")
                session.add(source)
                session.flush()
            session.execute(
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
            session.commit()


class _FailingConnector(Connector):
    """fetch()가 즉시 예외를 던지는 가짜 커넥터 — 소스 격리 검증용."""

    def fetch(self) -> Iterable[dict[str, Any]]:
        raise RuntimeError("simulated source outage")
        yield  # pragma: no cover — 위 raise로 도달 불가, generator로 만들기 위한 yield

    def normalize(self, payload: dict[str, Any]) -> NormalizedDoc:  # pragma: no cover
        raise NotImplementedError

    def upsert(self, doc: NormalizedDoc) -> None:  # pragma: no cover
        raise NotImplementedError


def _audit_actions(db: sessionmaker) -> list[str]:
    with db() as s:
        return list(s.execute(select(AuditLog.action)).scalars().all())


def test_run_daily_isolates_source_failure(db: sessionmaker) -> None:
    """실패 소스는 error로 기록되고 예외가 위로 새지 않으며, 다른 소스 수집은 계속된다."""
    report = run_daily(
        _BRIEF_DATE,
        connectors=[("good", _GoodConnector()), ("failing", _FailingConnector())],
        embedder=None,
        digester=None,
        analyzer=None,
    )
    by_name = {s.name: s for s in report.sources}
    assert by_name["good"].status == "ok"
    assert by_name["good"].attempted == 2
    assert by_name["failing"].status == "error"
    assert by_name["failing"].error is not None
    # audit_log: 소스별 source_fetch 2행 + daily_run 요약 1행.
    actions = _audit_actions(db)
    assert actions.count("source_fetch") == 2
    assert actions.count("daily_run") == 1


def test_run_daily_empty_day_no_crash(db: sessionmaker) -> None:
    """수집 소스가 없거나 전부 실패해도 크래시 없이 빈/degraded 다이제스트로 완료한다."""
    report = run_daily(
        _BRIEF_DATE,
        connectors=[("failing", _FailingConnector())],
        embedder=None,
        digester=None,
        analyzer=None,
    )
    assert report.digest_status in {"empty", "degraded"}
    assert report.embedded == 0
    with db() as s:
        digests = s.execute(select(func.count()).select_from(DailyDigest)).scalar_one()
    assert digests >= 1  # build_digest는 빈 날에도 최소 1행을 쓴다


def test_run_daily_concurrency_guard(db: sessionmaker) -> None:
    """다른 연결이 _DAILY_LOCK_KEY를 먼저 잡고 있으면 run_daily는 DailyRunAlreadyRunning."""
    from app.db import engine

    holder = engine.connect()
    try:
        acquired = holder.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": _DAILY_LOCK_KEY}
        ).scalar()
        assert acquired  # 사전 점유 성공
        raised = False
        try:
            run_daily(_BRIEF_DATE, connectors=[], embedder=None, digester=None, analyzer=None)
        except DailyRunAlreadyRunning:
            raised = True
        assert raised
    finally:
        holder.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _DAILY_LOCK_KEY})
        holder.close()


def test_run_daily_runs_pipeline_and_digest(db: sessionmaker) -> None:
    """good 커넥터가 적재 → run_daily 후 그날 brief_items + DailyDigest 행이 존재한다."""
    report = run_daily(
        _BRIEF_DATE,
        connectors=[("good", _GoodConnector(count=2))],
        embedder=None,
        digester=None,
        analyzer=None,
    )
    assert report.sources == [SourceResult(name="good", status="ok", attempted=2)]
    with db() as s:
        items = s.execute(
            select(func.count()).select_from(BriefItem).where(BriefItem.brief_date == _BRIEF_DATE)
        ).scalar_one()
        digests = s.execute(
            select(func.count())
            .select_from(DailyDigest)
            .where(DailyDigest.brief_date == _BRIEF_DATE)
        ).scalar_one()
    assert items == 2  # 적재된 문서 2건 → 단독 클러스터 2 → brief_item 2
    assert digests >= 1  # analyzer/digester 없어 ok 인용 0 → degraded/empty 다이제스트 1행
