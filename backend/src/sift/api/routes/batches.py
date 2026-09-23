"""Submitting work: pull a window of arXiv listings into the papers table."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status

from sift.api.deps import Http, Session
from sift.api.schemas import BatchRequest, BatchResult
from sift.ingest.listing import ListingError, QueryRejected, fetch_listing
from sift.storage.papers import add_papers

router = APIRouter(prefix="/batches", tags=["batches"])


@router.post("")
async def create_batch(request: BatchRequest, session: Session, http: Http) -> BatchResult:
    """Fetch the listing and store what is new, before answering."""
    until = datetime.now(UTC).date()
    if request.since > until:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "since is in the future")
    try:
        listing = await fetch_listing(http, request.category, request.since, until)
    except QueryRejected as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    except ListingError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    added = await add_papers(session, listing.papers)
    await session.commit()
    return BatchResult(
        category=request.category,
        since=request.since,
        until=until,
        matched=listing.total,
        fetched=len(listing.papers),
        added=added,
    )
