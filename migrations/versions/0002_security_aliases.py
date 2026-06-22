"""security_aliases (STAGE1_DESIGN 6.4 ticker-link alias dictionary)

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "security_aliases",
        sa.Column("alias", sa.String, primary_key=True),
        sa.Column("ticker", sa.String, primary_key=True),
        sa.Column("market", sa.String, primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("security_aliases")
