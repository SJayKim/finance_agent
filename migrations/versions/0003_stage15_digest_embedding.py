"""stage1.5 daily digests + embedding dim 1024 (STAGE1.5_DESIGN §6/§7)

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_digests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("brief_date", sa.Date, nullable=False),
        sa.Column("section", sa.String, nullable=False),
        sa.Column("heading", sa.Text, nullable=True),
        sa.Column("body_text", sa.Text, nullable=True),
        sa.Column("status", sa.String, nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("brief_date", "section", name="uq_daily_digests_date_section"),
    )

    op.create_table(
        "digest_sources",
        sa.Column("digest_id", sa.Integer, sa.ForeignKey("daily_digests.id"), primary_key=True),
        sa.Column("brief_item_id", sa.Integer, sa.ForeignKey("brief_items.id"), primary_key=True),
    )

    # 임베딩 차원 1024 고정 (그린필드 — 컬럼 전부 NULL이라 타입 변경 안전). raw SQL로 확실하게.
    op.execute("ALTER TABLE raw_documents ALTER COLUMN embedding TYPE vector(1024)")
    op.execute("ALTER TABLE clusters ALTER COLUMN centroid TYPE vector(1024)")

    # HNSW cosine 인덱스 — 정규화된 문장 임베딩의 RAG 코사인 유사도 검색용.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_raw_documents_embedding_hnsw "
        "ON raw_documents USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_raw_documents_embedding_hnsw")
    op.execute("ALTER TABLE clusters ALTER COLUMN centroid TYPE vector")
    op.execute("ALTER TABLE raw_documents ALTER COLUMN embedding TYPE vector")
    op.drop_table("digest_sources")
    op.drop_table("daily_digests")
