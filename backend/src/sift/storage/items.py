"""Claiming batch items for a stage, and recording how the stage went.

The same protocol as batches: a claim locks one waiting item with
`FOR UPDATE SKIP LOCKED` and stamps it with a lease, a fresh UUID and an expiry.
The work happens with no transaction open. Every write that records the outcome
is guarded by the lease, so a worker that outlived its lease writes nothing and
the item's next holder is not overwritten.

The caller owns the transaction; nothing here commits.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sift.retry import GiveUp, NextStep, RetryIn
from sift.storage.models import BatchItem as ItemRow
from sift.storage.models import Paper as PaperRow
from sift.types import ItemState, Stage


@dataclass(frozen=True, slots=True)
class ItemClaim:
    """What a worker holds while one item goes through one stage."""

    item_id: int
    lease: UUID
    stage: Stage
    attempts: int
    paper_id: int
    arxiv_id: str
    title: str
    abstract: str


async def claim_item(session: AsyncSession, stage: Stage, lease_for: timedelta) -> ItemClaim | None:
    """Take the oldest item waiting for `stage` that nobody holds and that is due."""
    now = func.now()
    candidate = (
        select(ItemRow, PaperRow)
        .join(PaperRow, PaperRow.id == ItemRow.paper_id)
        .where(
            ItemRow.state == stage,
            or_(ItemRow.lease_expires_at.is_(None), ItemRow.lease_expires_at < now),
            or_(ItemRow.not_before.is_(None), ItemRow.not_before <= now),
        )
        .order_by(ItemRow.id)
        .limit(1)
        .with_for_update(of=ItemRow, skip_locked=True)
    )
    found = (await session.execute(candidate)).first()
    if found is None:
        return None
    item, paper = found._tuple()
    lease = uuid4()
    await session.execute(
        update(ItemRow)
        .where(ItemRow.id == item.id)
        .values(lease=lease, lease_expires_at=now + lease_for)
    )
    return ItemClaim(
        item_id=item.id,
        lease=lease,
        stage=stage,
        attempts=item.attempts,
        paper_id=paper.id,
        arxiv_id=paper.arxiv_id,
        title=paper.title,
        abstract=paper.abstract,
    )


async def advance_item(session: AsyncSession, claim: ItemClaim, to: ItemState) -> bool:
    """Move a claimed item on to `to` and release it. False, writing nothing, if the
    lease is gone — the caller must then write nothing else either."""
    guarded = (
        update(ItemRow)
        .where(ItemRow.id == claim.item_id, ItemRow.lease == claim.lease)
        .values(
            state=to,
            attempts=0,
            last_error=None,
            not_before=None,
            lease=None,
            lease_expires_at=None,
        )
        .returning(ItemRow.id)
    )
    return (await session.scalars(guarded)).first() is not None


async def record_item_failure(
    session: AsyncSession, claim: ItemClaim, error: str, step: NextStep
) -> bool:
    """Note a failed attempt and release the item: back to wait for the same stage
    after the delay, or `dead` with the reason kept. False if the lease was lost."""
    not_before: ColumnElement[datetime] | None
    match step:
        case RetryIn(delay):
            state: ItemState = claim.stage
            not_before = func.now() + timedelta(seconds=delay)
            last_error = error
        case GiveUp(reason):
            state, not_before, last_error = "dead", None, reason
    guarded = (
        update(ItemRow)
        .where(ItemRow.id == claim.item_id, ItemRow.lease == claim.lease)
        .values(
            state=state,
            attempts=ItemRow.attempts + 1,
            last_error=last_error,
            not_before=not_before,
            lease=None,
            lease_expires_at=None,
        )
        .returning(ItemRow.id)
    )
    return (await session.scalars(guarded)).first() is not None
