"""SQLAlchemy models. The only classes in this package."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
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

    # Extracted text lives in object storage; arXiv forbids rehosting the PDF.
    text_s3_key: Mapped[str | None] = mapped_column(Text, default=None)
    # Hash of the extracted text, so the same document submitted twice is one row.
    content_hash: Mapped[str | None] = mapped_column(String(64), default=None)

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
    """One paper as part of one batch. The stages that act on a paper advance `state`."""

    __tablename__ = "batch_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"))
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    state: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("batch_id", "paper_id"),
        CheckConstraint("state in ('pending')", name="ck_batch_items_state"),
    )
