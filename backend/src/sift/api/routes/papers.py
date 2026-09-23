"""Listing papers, ranked against the wishlist."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query

from sift.api.deps import RankedAgainst, Session
from sift.api.schemas import PaperPage
from sift.storage.papers import list_papers
from sift.types import Order

router = APIRouter(prefix="/papers", tags=["papers"])


@router.get("")
async def get_papers(
    session: Session,
    profile: RankedAgainst,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    days: Annotated[
        int | None, Query(ge=1, le=3650, description="Published within this many days")
    ] = None,
    order: Order = "rank",
) -> PaperPage:
    """Papers with their verdicts, best first; `days` keeps to recent ones."""
    since = None if days is None else datetime.now(UTC) - timedelta(days=days)
    page = await list_papers(
        session, profile=profile.name, limit=limit, offset=offset, since=since, order=order
    )
    return PaperPage.of(page)
