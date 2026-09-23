"""Harvesting: a worker loop that advances batches one listing page at a time.

A step claims a batch, asks arXiv for its next page with no transaction open,
then records the outcome. Nothing is held in memory between steps, so a worker
killed at any point loses at most the page it was fetching: its lease runs out
and the next claim resumes from the last recorded resumption token.
"""

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sift.core.batches import after_failure
from sift.ingest.listing import ListingError, QueryRejected, fetch_page, first_page, next_page
from sift.storage.batches import claim_batch, record_failure, record_page
from sift.storage.engine import session_scope

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Pacing:
    """How a worker spends its time.

    `lease` must outlast one page fetch, including its HTTP timeout, or a slow
    but healthy worker loses its batch mid-page.
    """

    lease: timedelta
    between_pages: timedelta
    idle_poll: timedelta


async def harvest_step(
    factory: async_sessionmaker[AsyncSession], http: httpx.AsyncClient, pacing: Pacing
) -> bool:
    """Advance one batch by one page. False when there was nothing to claim."""
    async with session_scope(factory) as session:
        claim = await claim_batch(session, pacing.lease)
    if claim is None:
        return False

    params = (
        next_page(claim.resumption_token)
        if claim.resumption_token is not None
        else first_page(claim.category, claim.since, claim.until)
    )
    try:
        listing = await fetch_page(http, params)
    except ListingError as error:
        outcome = after_failure(claim.attempts + 1, retryable=not isinstance(error, QueryRejected))
        async with session_scope(factory) as session:
            kept = await record_failure(session, claim, str(error), outcome)
        logger.warning("batch %d: %s (%s)", claim.batch_id, error, outcome.state)
    else:
        async with session_scope(factory) as session:
            kept = await record_page(
                session,
                claim,
                papers=listing.papers,
                resumption_token=listing.resumption_token,
                next_page_after=pacing.between_pages,
            )
    if not kept:
        logger.warning("batch %d: lease lost before the step was recorded", claim.batch_id)
    return True


async def run_worker(
    factory: async_sessionmaker[AsyncSession],
    http: httpx.AsyncClient,
    pacing: Pacing,
    stop: asyncio.Event,
) -> None:
    """Step until `stop` is set, resting for `idle_poll` whenever there is nothing to do.

    An unexpected error in one step is logged and the loop carries on: the
    batch's lease runs out and it is claimed again, so no step is lost.
    """
    while not stop.is_set():
        try:
            worked = await harvest_step(factory, http, pacing)
        except Exception:
            logger.exception("harvest step failed")
            worked = False
        if not worked:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=pacing.idle_poll.total_seconds())
