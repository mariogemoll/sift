"""Liveness plus the two facts that actually go wrong: the database and the schema."""

from fastapi import APIRouter
from sqlalchemy.exc import SQLAlchemyError

from sift.api.deps import Session
from sift.api.schemas import HealthResponse
from sift.storage.schema import current_revision, ping

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: Session) -> HealthResponse:
    try:
        await ping(session)
        revision = await current_revision(session)
    except (SQLAlchemyError, OSError):
        return HealthResponse(ok=False, database=False, revision=None)
    return HealthResponse(ok=revision is not None, database=True, revision=revision)
