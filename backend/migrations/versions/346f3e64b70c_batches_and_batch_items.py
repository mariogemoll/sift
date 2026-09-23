"""batches and batch items

Revision ID: 346f3e64b70c
Revises: c426cc73ab64
Create Date: 2026-09-23 18:12:20.294293
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "346f3e64b70c"
down_revision: str | None = "c426cc73ab64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("since", sa.Date(), nullable=False),
        sa.Column("until", sa.Date(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("resumption_token", sa.Text(), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("added", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state in ('queued', 'harvesting', 'done', 'failed')", name="ck_batches_state"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_batches_unfinished",
        "batches",
        ["created_at"],
        unique=False,
        postgresql_where="state in ('queued', 'harvesting')",
    )
    op.create_table(
        "batch_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("state in ('pending')", name="ck_batch_items_state"),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "paper_id"),
    )


def downgrade() -> None:
    op.drop_table("batch_items")
    op.drop_index(
        "ix_batches_unfinished",
        table_name="batches",
        postgresql_where="state in ('queued', 'harvesting')",
    )
    op.drop_table("batches")
