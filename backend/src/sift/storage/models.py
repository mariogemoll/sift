"""SQLAlchemy models. The only classes in this package."""

from datetime import datetime

from sqlalchemy import ARRAY, DateTime, Index, String, Text, func
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
