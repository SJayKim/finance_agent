"""임베딩 레이어 테스트 — sentence-transformers 불필요(FakeEmbedder + None 경로).

순수 단위(결정성·정규화·차원·텍스트 결합·get_embedder None) + DB 통합(embed_documents
멱등 채움). 실 모델은 절대 로드하지 않는다 — get_embedder는 embedding_model을 None으로
몽키패치해 라이브러리 부재에 의존하지 않고 None 경로를 검증한다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import embed as embed_mod
from app.config import settings
from app.embed import FakeEmbedder, document_embed_text, get_embedder
from app.models import RawDocument, Source
from app.pipeline.embed import embed_documents


def test_fake_embedder_is_deterministic_and_normalized() -> None:
    e = FakeEmbedder()
    v1 = e.embed(["삼성전자 어닝 서프라이즈"])[0]
    v2 = e.embed(["삼성전자 어닝 서프라이즈"])[0]
    assert v1 == v2  # 같은 텍스트 → 동일 벡터
    assert len(v1) == settings.embedding_dim == 1024
    norm = sum(x * x for x in v1) ** 0.5
    assert abs(norm - 1.0) < 1e-9  # L2 정규화


def test_fake_embedder_differs_by_text() -> None:
    e = FakeEmbedder()
    a = e.embed(["비트코인 1억원 돌파"])[0]
    b = e.embed(["한국은행 기준금리 동결"])[0]
    assert a != b


def test_get_embedder_returns_none_when_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "embedding_model", None)
    embed_mod.get_embedder.cache_clear()
    try:
        assert get_embedder() is None
    finally:
        embed_mod.get_embedder.cache_clear()  # 다른 테스트에 캐시 누수 방지


def test_document_embed_text_combines_title_summary() -> None:
    assert document_embed_text("제목", "요약") == "제목\n\n요약"
    assert document_embed_text("제목", None) == "제목"
    assert document_embed_text(None, "요약") == "요약"
    assert document_embed_text(None, None) == ""
    assert document_embed_text("", "") == ""


_PUBLISHED = datetime(2026, 6, 20, 12, tzinfo=timezone.utc)


def _seed_two_docs(db: sessionmaker) -> None:
    """텍스트 있는 문서 1 + 제목·요약 빈 문서 1."""
    with db() as s:
        src = Source(name="test-src", kind="news")
        s.add(src)
        s.flush()
        s.add_all(
            [
                RawDocument(
                    source_id=src.id,
                    external_id="has-text",
                    title="삼성전자 어닝 서프라이즈",
                    summary="2분기 영업익 시장 기대 상회",
                    published_at=_PUBLISHED,
                ),
                RawDocument(
                    source_id=src.id,
                    external_id="empty",
                    title=None,
                    summary=None,
                    published_at=_PUBLISHED,
                ),
            ]
        )
        s.commit()


def test_embed_documents_fills_null_embeddings_idempotent(db: sessionmaker) -> None:
    _seed_two_docs(db)
    with db() as s:
        n = embed_documents(s, FakeEmbedder())
        s.commit()
    assert n == 1  # 텍스트 있는 1건만
    with db() as s:
        rows = {r.external_id: r for r in s.execute(select(RawDocument)).scalars().all()}
    assert rows["has-text"].embedding is not None
    assert len(rows["has-text"].embedding) == 1024
    assert rows["empty"].embedding is None  # 빈 텍스트는 NULL 유지
    with db() as s:
        again = embed_documents(s, FakeEmbedder())
        s.commit()
    assert again == 0  # 멱등 — 새로 임베딩할 게 없음


def test_embed_documents_noop_when_embedder_none(db: sessionmaker) -> None:
    _seed_two_docs(db)
    with db() as s:
        n = embed_documents(s, None)
        s.commit()
    assert n == 0
    with db() as s:
        embedded = (
            s.execute(select(RawDocument).where(RawDocument.embedding.is_not(None))).scalars().all()
        )
    assert embedded == []  # 변화 없음
