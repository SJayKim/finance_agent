"""Stage 1.5 캡스톤 통합 테스트 (실 Postgres + pgvector).

크로스-페이즈 시임을 한 흐름으로 검증한다: embed 단계가 채운 벡터를 RAG 검색이 실제로
회수하는가. 단위 테스트(test_rag_chat.py·test_embed*)는 두 단계를 따로 덮지만, 여기선
embed_documents → search_citation_spans를 같은 코퍼스 위에서 이어 돌려 "임베딩이 검색
재료가 된다"는 단일 계약을 증명한다.

FakeEmbedder는 결정론적 — 같은 텍스트는 같은 정규화 벡터(코사인 거리 0)라 정확-텍스트
질의는 rank 1이 보장된다. 네트워크·실 모델·Anthropic 없이 오프라인.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.collector.base import Connector, NormalizedDoc
from app.embed import FakeEmbedder, document_embed_text
from app.models import BriefItem, Citation, DailyDigest, RawDocument, Source
from app.pipeline.embed import embed_documents
from app.runner import run_daily
from app.web.queries import search_citation_spans

# 프로덕션(runner.main)처럼 KST 오늘을 기준일로 쓴다. run_daily가 수집한 문서는
# fetched_at=now()로 적재되므로, _count_embedded의 brief_date 윈도(KST 종일)에 들려면
# 기준일이 오늘이어야 한다. 고정 과거일이면 그날 외엔 embedded 카운트가 0이 돼 깨진다.
_KST = timezone(timedelta(hours=9))
_BRIEF_DATE = datetime.now(_KST).date()

# 명확히 구별되는 세 문서(제목+요약). embed 텍스트가 서로 멀어 정확-텍스트 질의의 rank 1이 안정.
_DOCS = [
    (
        "semi",
        "반도체 수출 호조",
        "메모리 가격 반등에 8월 반도체 수출이 급증했다",
        "반도체 수출이 급증",
    ),
    (
        "btc",
        "비트코인 급등",
        "비트코인이 10만 달러를 돌파하며 위험자산 선호가 강해졌다",
        "비트코인 10만 달러 돌파",
    ),
    ("commodity", "원자재 가격", "국제 유가와 구리 등 원자재 가격이 전반적으로 하락했다", None),
]


def test_embed_stage_output_is_retrievable_by_rag(db: sessionmaker) -> None:
    """embed 단계가 채운 벡터를 RAG 검색이 회수한다 (크로스-페이즈 시임 1개)."""
    with db() as s:
        src = Source(name="capstone-src", kind="news")
        s.add(src)
        s.flush()

        docs: dict[str, RawDocument] = {}
        for ext, title, summary, _cited in _DOCS:
            doc = RawDocument(source_id=src.id, external_id=ext, title=title, summary=summary)
            s.add(doc)
            docs[ext] = doc
        s.flush()

        item = BriefItem(brief_date=_BRIEF_DATE, cluster_id=None, status="ok")
        s.add(item)
        s.flush()

        # 세 문서 중 2건에만 인용(semi·btc). commodity는 인용 없음 — 검색 후보에서 자연 제외.
        for ext in ("semi", "btc"):
            cited = next(c for e, _t, _su, c in _DOCS if e == ext)
            assert cited is not None
            s.add(
                Citation(
                    brief_item_id=item.id,
                    raw_document_id=docs[ext].id,
                    cited_text=cited,
                )
            )
        s.commit()

        # embed 전: 세 문서 모두 embedding NULL.
        assert all(d.embedding is None for d in docs.values())

        embedder = FakeEmbedder()
        embedded = embed_documents(s, embedder)
        s.commit()

        # 세 문서 모두 제목+요약이 비어있지 않으므로 3건 임베딩.
        assert embedded == 3
        for ext in ("semi", "btc"):
            row = s.get(RawDocument, docs[ext].id)
            assert row is not None and row.embedding is not None
            assert len(row.embedding) == 1024

        # 같은 FakeEmbedder로 semi 문서의 임베딩 텍스트를 그대로 질의 → 코사인 거리 0 → rank 1.
        semi = docs["semi"]
        query_text = document_embed_text(semi.title, semi.summary)
        query_vec = embedder.embed([query_text])[0]
        views = search_citation_spans(s, query_vec, top_k=2)

    assert views, "RAG 검색이 임베딩된 인용을 회수해야 한다"
    assert views[0].cited_text == "반도체 수출이 급증"  # 질의한 semi 문서의 인용이 최근접
    cited_texts = {v.cited_text for v in views}
    assert "원자재" not in " ".join(cited_texts)  # 인용 없는 commodity는 결과에 없음
    assert cited_texts <= {"반도체 수출이 급증", "비트코인 10만 달러 돌파"}


class _FakeConn(Connector):
    """run_daily용 오프라인 커넥터: 2건의 raw_document를 멱등 upsert(네트워크 없음)."""

    def __init__(self, db: sessionmaker) -> None:
        self._db = db

    def fetch(self) -> Iterable[dict[str, Any]]:
        yield {"external_id": "fake-1", "title": "반도체 수출 호조", "summary": "수출 급증"}
        yield {"external_id": "fake-2", "title": "비트코인 급등", "summary": "10만 달러 돌파"}

    def normalize(self, payload: dict[str, Any]) -> NormalizedDoc:
        return NormalizedDoc(
            source="fake-src",
            external_id=payload["external_id"],
            published_at=None,
            title=payload["title"],
            summary=payload["summary"],
            body=None,
            url=None,
            lang="ko",
            raw_payload=payload,
        )

    def upsert(self, doc: NormalizedDoc) -> None:
        with self._db() as s:
            source = s.scalar(select(Source).where(Source.name == doc.source))
            if source is None:
                source = Source(name=doc.source, kind="news")
                s.add(source)
                s.flush()
            s.add(
                RawDocument(
                    source_id=source.id,
                    external_id=doc.external_id,
                    title=doc.title,
                    summary=doc.summary,
                )
            )
            s.commit()


def test_run_daily_produces_searchable_corpus(db: sessionmaker) -> None:
    """run_daily가 수집→파이프라인→임베딩→다이제스트를 오프라인으로 한 흐름에 묶는다(보너스).

    실 모델·Anthropic·네트워크 없이 FakeEmbedder + 가짜 커넥터로. digester=None이라
    다이제스트는 degraded지만 DailyDigest 행은 1건 존재한다(빈 날 정직 보장).
    """
    report = run_daily(
        _BRIEF_DATE,
        connectors=[("fake", _FakeConn(db))],
        embedder=FakeEmbedder(),
        digester=None,
    )

    assert report.brief_date == _BRIEF_DATE
    assert [s.status for s in report.sources] == ["ok"]
    assert report.embedded == 2  # 수집된 2건이 모두 임베딩됨

    with db() as s:
        embedded = s.execute(
            select(func.count()).select_from(RawDocument).where(RawDocument.embedding.is_not(None))
        ).scalar_one()
        assert embedded == 2
        digests = (
            s.execute(select(DailyDigest).where(DailyDigest.brief_date == _BRIEF_DATE))
            .scalars()
            .all()
        )
        assert len(digests) == 1  # digester=None → degraded 행 1건 (다이제스트 존재 보장)
