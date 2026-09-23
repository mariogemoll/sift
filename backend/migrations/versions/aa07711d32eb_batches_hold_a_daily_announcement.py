"""batches hold a daily announcement

Revision ID: aa07711d32eb
Revises: 6caf997255c1
Create Date: 2026-09-23 20:25:09.081804
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "aa07711d32eb"
down_revision: str | None = "6caf997255c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A batch is one category's announcement now: no window, no pages to resume.
    op.add_column("batches", sa.Column("announced", sa.Date(), nullable=True))
    op.drop_column("batches", "resumption_token")
    op.drop_column("batches", "until")
    op.drop_column("batches", "pages")
    op.drop_column("batches", "since")


def downgrade() -> None:
    # The window a batch covered is gone; the day it was made stands in for both
    # ends, and it had no pages to resume.
    op.add_column("batches", sa.Column("since", sa.Date(), nullable=True))
    op.add_column("batches", sa.Column("until", sa.Date(), nullable=True))
    op.add_column("batches", sa.Column("pages", sa.Integer(), nullable=True))
    op.add_column("batches", sa.Column("resumption_token", sa.Text(), nullable=True))
    op.execute("update batches set since = created_at::date, until = created_at::date, pages = 0")
    for column in ("since", "until", "pages"):
        op.alter_column("batches", column, nullable=False)
    op.drop_column("batches", "announced")
