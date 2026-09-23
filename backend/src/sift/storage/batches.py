"""Reads and writes over batches and their items. Functions taking a session.

Workers coordinate through these rows alone. A worker claims a batch by locking
it with `FOR UPDATE SKIP LOCKED`, so two workers never claim the same one, and
stamps it with a lease: a fresh UUID and an expiry. Every write that follows is
guarded by that UUID. A worker that hangs past its expiry loses the batch to the
next claim, and its late writes then match nothing and are refused.

The caller owns the transaction; nothing here commits.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sift.core.retry import GiveUp, NextStep, RetryIn
from sift.core.types import Batch, BatchState, ItemState, Paper, batch_status
from sift.storage.models import Batch as BatchRow
from sift.storage.models import BatchItem as BatchItemRow
from sift.storage.models import Paper as PaperRow
from sift.storage.papers import add_papers

UNFINISHED: tuple[BatchState, ...] = ("queued", "harvesting")


@dataclass(frozen=True, slots=True)
class Claim:
    """What a worker holds while it fetches one batch's announcement."""

    batch_id: int
    lease: UUID
    category: str
    attempts: int


async def _progress(
    session: AsyncSession, batch_ids: Sequence[int]
) -> Mapping[int, Mapping[ItemState, int]]:
    """How many items of each batch are in each state; states with none are absent."""
    counts: defaultdict[int, dict[ItemState, int]] = defaultdict(dict)
    rows = await session.execute(
        select(BatchItemRow.batch_id, BatchItemRow.state, func.count())
        .where(BatchItemRow.batch_id.in_(batch_ids))
        .group_by(BatchItemRow.batch_id, BatchItemRow.state)
    )
    for batch_id, state, count in rows.tuples():
        counts[batch_id][cast(ItemState, state)] = count
    return counts


def _to_domain(row: BatchRow, progress: Mapping[ItemState, int]) -> Batch:
    state = cast(BatchState, row.state)
    return Batch(
        id=row.id,
        category=row.category,
        state=state,
        announced=row.announced,
        added=row.added,
        items=sum(progress.values()),
        progress=progress,
        status=batch_status(state, progress),
        attempts=row.attempts,
        last_error=row.last_error,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


async def create_batch(session: AsyncSession, category: str) -> Batch:
    row = BatchRow(category=category)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _to_domain(row, {})


async def get_batch(session: AsyncSession, batch_id: int) -> Batch | None:
    row = await session.get(BatchRow, batch_id, populate_existing=True)
    if row is None:
        return None
    return _to_domain(row, (await _progress(session, [row.id])).get(row.id, {}))


async def list_batches(session: AsyncSession, *, limit: int) -> tuple[Batch, ...]:
    """Newest first."""
    statement = (
        select(BatchRow).order_by(BatchRow.created_at.desc(), BatchRow.id.desc()).limit(limit)
    )
    rows = (await session.scalars(statement)).all()
    progress = await _progress(session, [row.id for row in rows])
    return tuple(_to_domain(row, progress.get(row.id, {})) for row in rows)


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
    return Claim(batch_id=row.id, lease=lease, category=row.category, attempts=row.attempts)


async def _add_items(session: AsyncSession, batch_id: int, papers: Sequence[Paper]) -> None:
    if not papers:
        return
    ids = select(PaperRow.id).where(PaperRow.arxiv_id.in_([paper.arxiv_id for paper in papers]))
    rows = [
        {"batch_id": batch_id, "paper_id": paper_id}
        for paper_id in (await session.scalars(ids)).all()
    ]
    await session.execute(insert(BatchItemRow).values(rows).on_conflict_do_nothing())


async def record_announcement(
    session: AsyncSession, claim: Claim, *, announced: date, papers: Sequence[Paper]
) -> bool:
    """Store the announcement's papers as the batch's items and finish the harvest.
    False, writing nothing, if the lease is gone."""
    now = func.now()
    guarded = (
        update(BatchRow)
        .where(BatchRow.id == claim.batch_id, BatchRow.lease == claim.lease)
        .values(
            state="done",
            announced=announced,
            attempts=0,
            last_error=None,
            not_before=None,
            lease=None,
            lease_expires_at=None,
            finished_at=now,
        )
        .returning(BatchRow.id)
    )
    if (await session.scalars(guarded)).first() is None:
        return False
    added = await add_papers(session, papers)
    await _add_items(session, claim.batch_id, papers)
    await session.execute(update(BatchRow).where(BatchRow.id == claim.batch_id).values(added=added))
    return True


async def record_failure(session: AsyncSession, claim: Claim, error: str, step: NextStep) -> bool:
    """Note a failed fetch and release the batch: due again after the delay, or
    failed with the reason kept. False if the lease was lost."""
    not_before: ColumnElement[datetime] | None
    finished_at: ColumnElement[datetime] | None
    match step:
        case RetryIn(delay):
            state: BatchState = "harvesting"
            not_before, finished_at, last_error = func.now() + timedelta(seconds=delay), None, error
        case GiveUp(reason):
            state, not_before, finished_at, last_error = "failed", None, func.now(), reason
    guarded = (
        update(BatchRow)
        .where(BatchRow.id == claim.batch_id, BatchRow.lease == claim.lease)
        .values(
            state=state,
            attempts=BatchRow.attempts + 1,
            last_error=last_error,
            not_before=not_before,
            lease=None,
            lease_expires_at=None,
            finished_at=finished_at,
        )
        .returning(BatchRow.id)
    )
    return (await session.scalars(guarded)).first() is not None
