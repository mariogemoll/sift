"""SQLAlchemy models. The only classes in this package."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base; Alembic autogenerate reads its metadata."""


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(primary_key=True)
    arxiv_id: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(Text)
    authors: Mapped[list[str]] = mapped_column(ARRAY(Text))
    categories: Mapped[list[str]] = mapped_column(ARRAY(Text))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    abstract: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_papers_published_at", "published_at"),)


class Batch(Base):
    """One harvest of a category over a window, advanced page by page by a worker.

    A worker owns a batch while `lease_expires_at` is in the future and it holds
    the matching `lease`. A worker that stops renewing loses the batch to the
    next one to claim it, and its later writes no longer match the lease.
    """

    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(64))
    since: Mapped[date] = mapped_column(Date)
    until: Mapped[date] = mapped_column(Date)
    state: Mapped[str] = mapped_column(String(16), default="queued")

    # Where the harvest stands: the token for the next page, or None before the first.
    resumption_token: Mapped[str | None] = mapped_column(Text, default=None)
    pages: Mapped[int] = mapped_column(default=0)
    added: Mapped[int] = mapped_column(default=0)

    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    lease: Mapped[UUID | None] = mapped_column(default=None)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    __table_args__ = (
        CheckConstraint(
            "state in ('queued', 'harvesting', 'done', 'failed')", name="ck_batches_state"
        ),
        # The claiming query scans unfinished batches only.
        Index(
            "ix_batches_unfinished",
            "created_at",
            postgresql_where="state in ('queued', 'harvesting')",
        ),
    )


class BatchItem(Base):
    """One paper as part of one batch, and the stage it waits for.

    `state` names the next stage: `screen`, then `fetch` and `judge` for a paper
    whose abstract passed, and `done` or `dead` at the end. A stage claims an
    item the way the harvest claims a batch — lease UUID and expiry, every write
    guarded by the lease — so a worker that dies mid-stage hands the item on.
    `attempts` and `last_error` describe failures in the current stage.
    """

    __tablename__ = "batch_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"))
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    state: Mapped[str] = mapped_column(String(16), default="screen")
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    lease: Mapped[UUID | None] = mapped_column(default=None)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("batch_id", "paper_id"),
        CheckConstraint(
            "state in ('screen', 'fetch', 'judge', 'done', 'dead')", name="ck_batch_items_state"
        ),
        # The claiming query scans unfinished items of one stage only.
        Index(
            "ix_batch_items_waiting",
            "state",
            "id",
            postgresql_where="state in ('screen', 'fetch', 'judge')",
        ),
    )


class PaperText(Base):
    """A paper's extracted text. The PDF it came from is not kept."""

    __tablename__ = "paper_texts"

    paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    pdf_bytes: Mapped[int]
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Judgment(Base):
    """A model's raw answers, keyed by a hash of everything it was given.

    Weights and thresholds are not part of the key, so re-weighting reads these
    back instead of asking again.
    """

    __tablename__ = "judgments"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(64))
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Verdict(Base):
    """Where a paper stands against one wishlist, from its latest stage of judging."""

    __tablename__ = "verdicts"

    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    profile: Mapped[str] = mapped_column(String(64))
    stage: Mapped[str] = mapped_column(String(8))
    eligible: Mapped[bool]
    total: Mapped[float]
    merit: Mapped[float | None]
    fit: Mapped[float]
    blocked_by: Mapped[list[str]] = mapped_column(ARRAY(Text))
    needs_review: Mapped[bool]
    notes: Mapped[list[str]] = mapped_column(ARRAY(Text))
    per_criterion: Mapped[dict[str, float]] = mapped_column(JSONB)
    judgment_key: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        PrimaryKeyConstraint("paper_id", "profile"),
        CheckConstraint("stage in ('screen', 'full')", name="ck_verdicts_stage"),
    )
