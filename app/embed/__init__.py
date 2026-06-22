"""임베딩 레이어 (STAGE1.5_DESIGN §4 트랙 D · §6 모델 게이트).

raw_documents의 정규화 텍스트(제목+요약)를 단위 정규화 벡터로 임베딩해 pgvector RAG
검색의 재료를 만든다. 경계:
- 실 모델(bge-m3, ~2GB)은 /trigger나 테스트 중 절대 로드되면 안 된다. run_pipeline은
  embedder를 자동 생성하지 않고(analyzer와 달리), 일일 오케스트레이터가 get_embedder()로
  명시 주입한다. 테스트는 FakeEmbedder(순수 파이썬)를 쓴다.
- Embedder는 Protocol — citations.py의 ImpactAnalyzer처럼 I/O 경계를 주입 가능하게.
- get_embedder()는 키 없는 분석기 비활성화와 같은 graceful degradation: 라이브러리가
  없거나 모델 미설정이면 None(크래시 금지).
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Protocol

from app.config import settings


class Embedder(Protocol):
    """텍스트 → 단위 정규화 벡터(dim=settings.embedding_dim) 임베딩 경계."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def document_embed_text(title: str | None, summary: str | None) -> str:
    """raw_document의 임베딩 대상 텍스트 = 제목 + "\n\n" + 요약 (citations._document_text와 동일 경계).

    body는 P5로 None일 수 있고 본문 청크 임베딩은 §4 D2로 이연 — 제목+요약만 임베딩한다.
    둘 다 비면 빈 문자열(임베딩 대상 없음 — embed_documents가 건너뛴다).
    """
    return "\n\n".join(part for part in (title, summary) if part)


class FakeEmbedder:
    """결정론적 순수 파이썬 임베더(numpy/torch 없음). 테스트·오프라인용.

    텍스트의 sha256을 시드로 dim개의 float를 펼친 뒤 L2 정규화한다. 같은 텍스트 → 같은
    벡터, 다른 텍스트 → 다른 벡터. 실 의미는 없지만 차원·정규화·결정성 계약은 실 모델과
    동일해 파이프라인 배선을 네트워크·모델 없이 검증한다.
    """

    def __init__(self, dim: int = settings.embedding_dim) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        # sha256(text)를 시드로 dim 바이트를 더 뽑아 [-1, 1) float로. 같은 텍스트 → 같은 바이트열.
        raw = bytearray()
        counter = 0
        while len(raw) < self.dim:
            digest = hashlib.sha256(f"{counter}\x00{text}".encode()).digest()
            raw.extend(digest)
            counter += 1
        values = [(byte / 127.5) - 1.0 for byte in raw[: self.dim]]
        norm = sum(v * v for v in values) ** 0.5
        if norm == 0.0:
            return values
        return [v / norm for v in values]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]


class SentenceTransformerEmbedder:
    """sentence-transformers(bge-m3 등) 실 모델 임베더. 모델은 __init__에서 1회 로드.

    sentence_transformers는 무거우므로 import를 __init__ 안으로 지연한다 — 모듈 import만으로는
    로드되지 않는다. dim 불일치(모델/config 드리프트)는 §6 게이트라 즉시 raise.
    """

    def __init__(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - 라이브러리 부재 경로
            raise RuntimeError(
                "sentence-transformers 미설치 — 임베딩은 opt-in: uv sync --extra embeddings"
            ) from exc
        self._model = SentenceTransformer(
            settings.embedding_model, device=settings.embedding_device
        )
        probe = self._model.encode(["dim probe"], normalize_embeddings=True)
        actual = len(probe[0])
        if actual != settings.embedding_dim:
            raise RuntimeError(
                f"임베딩 차원 불일치(§6 게이트): 모델 {settings.embedding_model}={actual}, "
                f"config embedding_dim={settings.embedding_dim}. Vector(dim) 마이그레이션 필요."
            )

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()


@lru_cache
def get_embedder() -> Embedder | None:
    """실 모델 임베더(캐시 1회 로드). 일일 오케스트레이터 전용 — run_pipeline은 호출하지 않는다.

    settings.embedding_model이 설정돼 있고 라이브러리가 import되면 SentenceTransformerEmbedder,
    그렇지 않으면 None(graceful — 키 없는 분석기 비활성화와 같은 패턴). dim 불일치는 게이트라
    raise(삼키지 않는다). lru_cache라 모델은 프로세스당 최대 1회 로드된다.
    """
    if settings.embedding_model is None:
        return None
    try:
        return SentenceTransformerEmbedder()
    except RuntimeError as exc:
        if isinstance(exc.__cause__, ImportError):
            return None  # 라이브러리 부재 → 비활성(graceful)
        raise  # dim 불일치 등 진짜 결함은 드러낸다
