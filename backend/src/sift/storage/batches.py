"""Reads and writes over batches and their items. Functions taking a session.

Workers coordinate through these rows alone. A worker claims a batch by locking
it with `FOR UPDATE SKIP LOCKED`, so two workers never claim the same one, and
stamps it with a lease: a fresh UUID and an expiry. Every write that follows is
guarded by that UUID. A worker that hangs past its expiry loses the batch to the
next claim, and its late writes then match nothing and are refused.

The caller owns the transaction; nothing here commits.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import ScalarSelect, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sift.core.batches import AfterFailure
from sift.core.types import Batch, BatchState, Paper
from sift.storage.models import Batch as BatchRow
from sift.storage.models import BatchItem as BatchItemRow
from sift.storage.models import Paper as PaperRow
from sift.storage.papers import add_papers

UNFINISHED: tuple[BatchState, ...] = ("queued", "harvesting")


@dataclass(frozen=True, slots=True)
class Claim:
    """What a worker holds while it works on one step of a batch."""

    batch_id: int
    lease: UUID
    category: str
    since: date
    until: date
    resumption_token: str | None
    attempts: int


def _items_count() -> ScalarSelect[int]:
    return (
        select(func.count())
        .where(BatchItemRow.batch_id == BatchRow.id)
        .correlate(BatchRow)
        .scalar_subquery()
    )


def _to_domain(row: BatchRow, items: int) -> Batch:
    return Batch(
        id=row.id,
        category=row.category,
        since=row.since,
        until=row.until,
        state=cast(BatchState, row.state),
        pages=row.pages,
        added=row.added,
        items=items,
        attempts=row.attempts,
        last_error=row.last_error,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


async def create_batch(session: AsyncSession, category: str, since: date, until: date) -> Batch:
    row = BatchRow(category=category, since=since, until=until)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _to_domain(row, items=0)


async def get_batch(session: AsyncSession, batch_id: int) -> Batch | None:
    found = (
        await session.execute(select(BatchRow, _items_count()).where(BatchRow.id == batch_id))
    ).first()
    return None if found is None else _to_domain(found[0], found[1])


async def list_batches(session: AsyncSession, *, limit: int) -> tuple[Batch, ...]:
    """Newest first."""
    statement = (
        select(BatchRow, _items_count())
        .order_by(BatchRow.created_at.desc(), BatchRow.id.desc())
        .limit(limit)
    )
    return tuple(_to_domain(row, items) for row, items in (await session.execute(statement)).all())


async def claim_batch(session: AsyncSession, lease_for: timedelta) -> Claim | None:
    """Take the oldest unfinished batch that nobody holds and that is due, if there is one."""
    now = func.now()
    candidate = (
        select(BatchRow)
        .where(
            BatchRow.state.in_(UNFINISHED),
            or_(BatchRow.lease_expires_at.is_(None), BatchRow.lease_expires_at < now),
            or_(BatchRow.not_before.is_(None), BatchRow.not_before <= now),
        )
        .order_by(BatchRow.created_at, BatchRow.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    row = (await session.scalars(candidate)).first()
    if row is None:
        return None
    lease = uuid4()
    await session.execute(
        update(BatchRow)
        .where(BatchRow.id == row.id)
        .values(state="harvesting", lease=lease, lease_expires_at=now + lease_for)
    )
    return Claim(
        batch_id=row.id,
        lease=lease,
        category=row.category,
        since=row.since,
        until=row.until,
        resumption_token=row.resumption_token,
        attempts=row.attempts,
    )


async def _add_items(session: AsyncSession, batch_id: int, papers: Sequence[Paper]) -> None:
    if not papers:
        return
    ids = select(PaperRow.id).where(PaperRow.arxiv_id.in_([paper.arxiv_id for paper in papers]))
    rows = [
        {"batch_id": batch_id, "paper_id": paper_id}
        for paper_id in (await session.scalars(ids)).all()
    ]
    await session.execute(insert(BatchItemRow).values(rows).on_conflict_do_nothing())


async def record_page(
    session: AsyncSession,
    claim: Claim,
    *,
    papers: Sequence[Paper],
    resumption_token: str | None,
    next_page_after: timedelta,
) -> bool:
    """Store one harvested page and release the batch. False, writing nothing, if the lease is gone.

    With no further token the batch is done. Otherwise it waits `next_page_after`
    before anyone may claim it for the next page, which is what paces the harvest.
    """
    now = func.now()
    finished = resumption_token is None
    guarded = (
        update(BatchRow)
        .where(BatchRow.id == claim.batch_id, BatchRow.lease == claim.lease)
        .values(
            state="done" if finished else "harvesting",
            resumption_token=resumption_token,
            pages=BatchRow.pages + 1,
            attempts=0,
            last_error=None,
            not_before=None if finished else now + next_page_after,
            lease=None,
            lease_expires_at=None,
            finished_at=now if finished else None,
        )
        .returning(BatchRow.id)
    )
    if (await session.scalars(guarded)).first() is None:
        return False
    added = await add_papers(session, papers)
    await _add_items(session, claim.batch_id, papers)
    await session.execute(
        update(BatchRow).where(BatchRow.id == claim.batch_id).values(added=BatchRow.added + added)
    )
    return True


async def record_failure(
    session: AsyncSession, claim: Claim, error: str, outcome: AfterFailure
) -> bool:
    """Note a failed step and release the batch, per `outcome`. False if the lease was lost."""
    now = func.now()
    failed = outcome.state == "failed"
    guarded = (
        update(BatchRow)
        .where(BatchRow.id == claim.batch_id, BatchRow.lease == claim.lease)
        .values(
            state=outcome.state,
            attempts=BatchRow.attempts + 1,
            last_error=error,
            not_before=None if failed else now + outcome.delay,
            lease=None,
            lease_expires_at=None,
            finished_at=now if failed else None,
        )
        .returning(BatchRow.id)
    )
    return (await session.scalars(guarded)).first() is not None
