"""papers

Revision ID: c426cc73ab64
Revises:
Create Date: 2026-09-23 15:15:33.290947
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c426cc73ab64"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "papers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("arxiv_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("authors", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("categories", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=False),
        sa.Column("text_s3_key", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("arxiv_id"),
    )
    op.create_index("ix_papers_published_at", "papers", ["published_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_papers_published_at", table_name="papers")
    op.drop_table("papers")
