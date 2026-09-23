"""Reads and writes over the papers table. Functions, not a repository class."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sift.core.types import Page, Paper
from sift.storage.models import Paper as PaperRow


def _to_domain(row: PaperRow) -> Paper:
    return Paper(
        arxiv_id=row.arxiv_id,
        title=row.title,
        authors=tuple(row.authors),
        categories=tuple(row.categories),
        published_at=row.published_at,
        abstract=row.abstract,
    )


async def count_papers(session: AsyncSession) -> int:
    total = await session.scalar(select(func.count()).select_from(PaperRow))
    return total or 0


async def list_papers(session: AsyncSession, *, limit: int, offset: int) -> Page[Paper]:
    """Newest first, so an empty database and a fresh batch both read sensibly."""
    statement = (
        select(PaperRow)
        .order_by(PaperRow.published_at.desc(), PaperRow.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.scalars(statement)).all()
    return Page(
        items=tuple(_to_domain(row) for row in rows),
        total=await count_papers(session),
        limit=limit,
        offset=offset,
    )
