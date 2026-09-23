"""Listing papers. Empty until ingestion lands."""

from typing import Annotated

from fastapi import APIRouter, Query

from sift.api.deps import Session
from sift.api.schemas import PaperPage
from sift.storage.papers import list_papers

router = APIRouter(prefix="/papers", tags=["papers"])


@router.get("")
async def get_papers(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaperPage:
    return PaperPage.of(await list_papers(session, limit=limit, offset=offset))
