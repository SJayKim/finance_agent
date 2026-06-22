"""embed 파이프라인 단계 (STAGE1.5_DESIGN §4 트랙 D · §6).

신규 raw_documents의 (제목+요약) 임베딩을 채운다 — pgvector RAG 검색의 재료. 멱등:
embedding IS NULL인 행만 채우므로 일일 실행마다 누적 코퍼스가 자연히 쌓인다. embedder가
None이면 no-op(graceful) — run_pipeline의 빠른 경로(/trigger·테스트)는 모델을 로드하지 않는다.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.embed import Embedder, document_embed_text
from app.models import RawDocument

# §4 D2 "공시는 body 청크" 임베딩은 이연: 별도 chunks 테이블이 필요하고, RAG grounding은
# citations(cited_text)에 묶이므로 검색은 여전히 동작한다. 현 범위는 제목+요약만 임베딩.


def embed_documents(session: Session, embedder: Embedder | None, *, batch_size: int = 64) -> int:
    """embedding IS NULL인 raw_documents를 배치로 임베딩해 채운다. 임베딩한 행 수를 반환(커밋은 호출자).

    embedder가 None이면 0(no-op). 제목+요약이 빈 행은 embedding을 NULL로 남긴다(임베딩 대상
    없음). 배치마다 flush한다.
    """
    if embedder is None:
        return 0
    rows = (
        session.execute(select(RawDocument).where(RawDocument.embedding.is_(None))).scalars().all()
    )
    embedded = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        pending = [(row, document_embed_text(row.title, row.summary)) for row in batch]
        pending = [(row, text) for row, text in pending if text]
        if not pending:
            continue
        vectors = embedder.embed([text for _row, text in pending])
        for (row, _text), vector in zip(pending, vectors, strict=True):
            row.embedding = vector
            embedded += 1
        session.flush()
    return embedded
