"""Reads and writes over extracted paper text. Functions taking a session."""

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sift.storage.models import PaperText


async def has_text(session: AsyncSession, paper_id: int) -> bool:
    found = await session.scalar(select(exists().where(PaperText.paper_id == paper_id)))
    return bool(found)


async def get_text(session: AsyncSession, paper_id: int) -> str | None:
    text: str | None = await session.scalar(
        select(PaperText.text).where(PaperText.paper_id == paper_id)
    )
    return text


async def put_text(
    session: AsyncSession, paper_id: int, *, text: str, content_hash: str, pdf_bytes: int
) -> None:
    """Store a paper's text. A paper that already has text keeps what it has: two
    workers fetching the same paper for different batches got the same document."""
    await session.execute(
        insert(PaperText)
        .values(paper_id=paper_id, text=text, content_hash=content_hash, pdf_bytes=pdf_bytes)
        .on_conflict_do_nothing(index_elements=[PaperText.paper_id])
    )
