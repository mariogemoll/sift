"""The wishlist papers are ranked against."""

from fastapi import APIRouter

from sift.api.deps import RankedAgainst
from sift.api.schemas import ProfileOut

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("")
async def get_profile(profile: RankedAgainst) -> ProfileOut:
    return ProfileOut.of(profile)
