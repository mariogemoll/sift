"""Submitting work and watching it. A worker does the harvesting; these only read and queue."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from sift.api.deps import RankedAgainst, Session
from sift.api.schemas import BatchOut
from sift.storage.batches import create_batch, get_batch, list_batches

router = APIRouter(prefix="/batches", tags=["batches"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def submit_batches(session: Session, profile: RankedAgainst) -> list[BatchOut]:
    """Queue one batch per category the wishlist names, in the wishlist's order.

    Each fetches its category's latest daily announcement when a worker gets to
    it; asking twice on one day asks for the same papers, which cost nothing twice.
    """
    batches = [await create_batch(session, category) for category in profile.categories]
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
