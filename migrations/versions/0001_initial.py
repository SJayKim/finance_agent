"""initial schema (STAGE1_DESIGN §8)

Revision ID: 0001
Revises:
Create Date: 2026-06-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String, nullable=False, unique=True),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("legal_basis", sa.Text, nullable=True),
        sa.Column("default_rate_limit", sa.Integer, nullable=True),
    )

    op.create_table(
        "raw_documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("external_id", sa.String, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("lang", sa.String, nullable=True),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("raw_payload", postgresql.JSONB, nullable=True),
        sa.Column("embedding", Vector(), nullable=True),
        sa.UniqueConstraint("source_id", "external_id", name="uq_raw_documents_source_external"),
    )

    op.create_table(
        "clusters",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("brief_date", sa.Date, nullable=False),
        sa.Column("centroid", Vector(), nullable=True),
        sa.Column(
            "representative_doc_id", sa.Integer, sa.ForeignKey("raw_documents.id"), nullable=True
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "cluster_members",
        sa.Column("cluster_id", sa.Integer, sa.ForeignKey("clusters.id"), primary_key=True),
        sa.Column(
            "raw_document_id", sa.Integer, sa.ForeignKey("raw_documents.id"), primary_key=True
        ),
    )

    op.create_table(
        "brief_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("brief_date", sa.Date, nullable=False),
        sa.Column("cluster_id", sa.Integer, sa.ForeignKey("clusters.id"), nullable=True),
        sa.Column("event_type", sa.String, nullable=True),
        sa.Column("direction", sa.String, nullable=True),
        sa.Column("confidence", sa.String, nullable=True),
        sa.Column("analysis_text", sa.Text, nullable=True),
        sa.Column("status", sa.String, nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "brief_item_tickers",
        sa.Column("brief_item_id", sa.Integer, sa.ForeignKey("brief_items.id"), primary_key=True),
        sa.Column("ticker", sa.String, primary_key=True),
        sa.Column("market", sa.String, nullable=False),
        sa.Column("link_precision", sa.Float, nullable=True),
        sa.Column("is_candidate", sa.Boolean, nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "citations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("brief_item_id", sa.Integer, sa.ForeignKey("brief_items.id"), nullable=False),
        sa.Column("raw_document_id", sa.Integer, sa.ForeignKey("raw_documents.id"), nullable=False),
        sa.Column("cited_text", sa.Text, nullable=False),
        sa.Column("char_start", sa.Integer, nullable=True),
        sa.Column("char_end", sa.Integer, nullable=True),
        sa.Column("source_published_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "coverage",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("analyst_id", sa.String, nullable=False),
        sa.Column("ticker", sa.String, nullable=True),
        sa.Column("sector", sa.String, nullable=True),
        sa.Column("market", sa.String, nullable=False),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actor", sa.String, nullable=True),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("coverage")
    op.drop_table("citations")
    op.drop_table("brief_item_tickers")
    op.drop_table("brief_items")
    op.drop_table("cluster_members")
    op.drop_table("clusters")
    op.drop_table("raw_documents")
    op.drop_table("sources")
