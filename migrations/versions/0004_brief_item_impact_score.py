"""brief_items.impact_score (STAGE2 impact ranking board)

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("brief_items", sa.Column("impact_score", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("brief_items", "impact_score")
