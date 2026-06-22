"""데이터 모델 (STAGE1_DESIGN §8). Postgres + pgvector.

설계 경계:
- embedding/centroid: 임베딩 모델 미정(§11.3) → vector 차원 미고정(`Vector()`).
- brief_items.event_type: taxonomy STAGE0-BLOCKED → enum 아닌 자유 문자열.
"""

from __future__ import annotations

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    kind: Mapped[str] = mapped_column(String)  # news | filing | price
    legal_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_rate_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RawDocument(Base):
    __tablename__ = "raw_documents"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_raw_documents_source_external"),
        # 정규화된 문장 임베딩의 RAG 코사인 유사도 검색용 HNSW 인덱스(0003). 차원은 Vector(1024).
        Index(
            "ix_raw_documents_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(String)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lang: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # dim 1024 = bge-m3/e5-large 권장군 (config.embedding_dim와 일치해야 함; 차원 변경 시 재임베딩+마이그레이션 필요).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)


class Cluster(Base):
    __tablename__ = "clusters"

    id: Mapped[int] = mapped_column(primary_key=True)
    brief_date: Mapped[date] = mapped_column(Date)
    # dim 1024 = bge-m3/e5-large 권장군 (config.embedding_dim와 일치해야 함; 차원 변경 시 재임베딩+마이그레이션 필요).
    centroid: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    representative_doc_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_documents.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClusterMember(Base):
    __tablename__ = "cluster_members"

    cluster_id: Mapped[int] = mapped_column(ForeignKey("clusters.id"), primary_key=True)
    raw_document_id: Mapped[int] = mapped_column(ForeignKey("raw_documents.id"), primary_key=True)


class BriefItem(Base):
    __tablename__ = "brief_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    brief_date: Mapped[date] = mapped_column(Date)
    cluster_id: Mapped[int | None] = mapped_column(ForeignKey("clusters.id"), nullable=True)
    event_type: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # STAGE0-BLOCKED: 자유 문자열
    direction: Mapped[str | None] = mapped_column(String, nullable=True)  # 긍정/부정/중립
    confidence: Mapped[str | None] = mapped_column(String, nullable=True)  # HIGH/MED/LOW
    analysis_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String)  # ok | degraded | empty
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BriefItemTicker(Base):
    __tablename__ = "brief_item_tickers"

    brief_item_id: Mapped[int] = mapped_column(ForeignKey("brief_items.id"), primary_key=True)
    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    market: Mapped[str] = mapped_column(String)  # KR | US | CRYPTO
    link_precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_candidate: Mapped[bool] = mapped_column(Boolean, default=False)  # §6.4 보류 표기


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(primary_key=True)
    brief_item_id: Mapped[int] = mapped_column(ForeignKey("brief_items.id"))
    raw_document_id: Mapped[int] = mapped_column(ForeignKey("raw_documents.id"))
    cited_text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Coverage(Base):
    __tablename__ = "coverage"

    id: Mapped[int] = mapped_column(primary_key=True)
    analyst_id: Mapped[str] = mapped_column(String)
    ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    market: Mapped[str] = mapped_column(String)  # KR | US | CRYPTO


class SecurityAlias(Base):
    """티커 링킹(§6.4) 별칭 사전 레퍼런스: alias(회사명/별칭) → (ticker, market).

    §9 coverage와 다른 축이다: '무엇을 커버하나'가 아니라 '텍스트에서 종목을 어떻게
    알아보나'. ticker_link가 이 테이블에서 사전을 적재한다(§2: 유니버스를 코드에 박지
    않고 DB 상태로 흐르게). 빈 테이블이면 링크 0건(정직). 같은 alias가 여러 종목이면 중의적.
    """

    __tablename__ = "security_aliases"

    alias: Mapped[str] = mapped_column(String, primary_key=True)
    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    market: Mapped[str] = mapped_column(String, primary_key=True)  # KR | US | CRYPTO


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class DailyDigest(Base):
    """일일 다이제스트 섹션 (STAGE1.5_DESIGN §7). (brief_date, section)당 1행, upsert 멱등."""

    __tablename__ = "daily_digests"
    __table_args__ = (
        UniqueConstraint("brief_date", "section", name="uq_daily_digests_date_section"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    brief_date: Mapped[date] = mapped_column(Date)
    section: Mapped[str] = mapped_column(
        String
    )  # 'macro' | 'sector:<섹터명>' (taxonomy STAGE0-BLOCKED)
    heading: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String)  # ok | degraded | empty
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DigestSource(Base):
    __tablename__ = "digest_sources"

    digest_id: Mapped[int] = mapped_column(ForeignKey("daily_digests.id"), primary_key=True)
    brief_item_id: Mapped[int] = mapped_column(ForeignKey("brief_items.id"), primary_key=True)
