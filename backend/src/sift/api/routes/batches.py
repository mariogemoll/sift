"""Submitting work and watching it. A worker does the harvesting; these only read and queue."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from sift.api.deps import RankedAgainst, Session
from sift.api.schemas import BatchOut, BatchRequest
from sift.storage.batches import create_batch, get_batch, list_batches

router = APIRouter(prefix="/batches", tags=["batches"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def submit_batch(
    request: BatchRequest, session: Session, profile: RankedAgainst
) -> list[BatchOut]:
    """Queue one harvest per category the wishlist names, in the wishlist's order.

    The window closes today, so each batch means the same thing when it runs.
    """
    until = datetime.now(UTC).date()
    if request.since > until:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "since is in the future")
    batches = [
        await create_batch(session, category, request.since, until)
        for category in profile.categories
    ]
    await session.commit()
    return [BatchOut.of(batch) for batch in batches]


@router.get("")
async def get_batches(
    session: Session, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[BatchOut]:
    """The most recent batches, newest first."""
    return [BatchOut.of(batch) for batch in await list_batches(session, limit=limit)]


@router.get("/{batch_id}")
async def get_one_batch(batch_id: int, session: Session) -> BatchOut:
    batch = await get_batch(session, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such batch")
    return BatchOut.of(batch)
