"""Questions about the database itself rather than about the domain."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def ping(session: AsyncSession) -> None:
    """Raise if the database is unreachable."""
    await session.execute(text("select 1"))


async def current_revision(session: AsyncSession) -> str | None:
    """The migration the database is on, or None if it has never been migrated.

    The table is looked up before it is read: a missing table would abort the
    surrounding transaction, and "not migrated yet" is an answer, not an error.
    """
    exists = await session.scalar(text("select to_regclass('public.alembic_version')"))
    if exists is None:
        return None
    revision = await session.scalar(text("select version_num from alembic_version limit 1"))
    return str(revision) if revision is not None else None
