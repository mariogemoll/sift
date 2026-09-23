"""pipeline stages, paper texts, judgments, verdicts

Revision ID: 6caf997255c1
Revises: 346f3e64b70c
Create Date: 2026-09-23 19:04:22.168118
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6caf997255c1"
down_revision: str | None = "346f3e64b70c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "judgments",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "paper_texts",
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("pdf_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "extracted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("paper_id"),
    )
    op.create_table(
        "verdicts",
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("profile", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=8), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("total", sa.Float(), nullable=False),
        sa.Column("merit", sa.Float(), nullable=True),
        sa.Column("fit", sa.Float(), nullable=False),
        sa.Column("blocked_by", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("per_criterion", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("judgment_key", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("stage in ('screen', 'full')", name="ck_verdicts_stage"),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("paper_id", "profile"),
    )
    # Items waiting after the harvest now wait for the screen, the first stage.
    op.drop_constraint("ck_batch_items_state", "batch_items", type_="check")
    op.execute("update batch_items set state = 'screen' where state = 'pending'")
    op.create_check_constraint(
        "ck_batch_items_state",
        "batch_items",
        "state in ('screen', 'fetch', 'judge', 'done', 'dead')",
    )
    op.add_column("batch_items", sa.Column("not_before", sa.DateTime(timezone=True), nullable=True))
    op.add_column("batch_items", sa.Column("lease", sa.Uuid(), nullable=True))
    op.add_column(
        "batch_items", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_batch_items_waiting",
        "batch_items",
        ["state", "id"],
        unique=False,
        postgresql_where="state in ('screen', 'fetch', 'judge')",
    )
    op.drop_column("papers", "content_hash")
    op.drop_column("papers", "text_s3_key")


def downgrade() -> None:
    op.add_column("papers", sa.Column("text_s3_key", sa.TEXT(), autoincrement=False, nullable=True))
    op.add_column(
        "papers",
        sa.Column("content_hash", sa.VARCHAR(length=64), autoincrement=False, nullable=True),
    )
    op.drop_index(
        "ix_batch_items_waiting",
        table_name="batch_items",
        postgresql_where="state in ('screen', 'fetch', 'judge')",
    )
    op.drop_column("batch_items", "lease_expires_at")
    op.drop_column("batch_items", "lease")
    op.drop_column("batch_items", "not_before")
    # Every stage collapses back into waiting; what was done is done again.
    op.drop_constraint("ck_batch_items_state", "batch_items", type_="check")
    op.execute("update batch_items set state = 'pending'")
    op.create_check_constraint("ck_batch_items_state", "batch_items", "state in ('pending')")
    op.drop_table("verdicts")
    op.drop_table("paper_texts")
    op.drop_table("judgments")
