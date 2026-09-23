"""Harvesting: a worker loop that fetches each queued batch's announcement.

A step claims a batch, asks arXiv for the category's latest announcement with no
transaction open, then records the outcome. Nothing is held in memory between
steps, so a worker killed at any point loses at most the request in hand: its
lease runs out and the next claim asks again.

Failures are sorted the way PDF downloads are — a refused or unknown category
gives up at once, server trouble backs off and tries again — and decided by the
same retry policy as every stage. The request takes a turn from the pacer the
downloads share, so listing and fetching together keep to arXiv's one request
at a time, and a Retry-After holds both.
"""

import asyncio
import contextlib
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sift.core.retry import Retryable, RetryPolicy, after_failure
from sift.ingest.announcements import fetch_announcement
from sift.ingest.failures import FetchFailed
from sift.ingest.pacing import Pacer
from sift.storage.batches import claim_batch, record_announcement, record_failure
from sift.storage.engine import session_scope

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Harvest:
    """Everything a harvest worker needs.

    `lease` must outlast one request, including its HTTP timeout and the wait for
    the pacer, or a slow but healthy worker loses its batch mid-request.
    """

    factory: async_sessionmaker[AsyncSession]
    http: httpx.AsyncClient
    arxiv: Pacer
    lease: timedelta
    policy: RetryPolicy
    draw: Callable[[], float] = random.random


async def harvest_step(harvest: Harvest) -> bool:
    """Fetch one batch's announcement. False when there was nothing to claim."""
    async with session_scope(harvest.factory) as session:
        claim = await claim_batch(session, harvest.lease)
    if claim is None:
        return False

    try:
        async with harvest.arxiv.turn():
            try:
                announcement = await fetch_announcement(harvest.http, claim.category)
            except FetchFailed as failed:
                match failed.failure:
                    case Retryable(retry_after=float(wait)):
                        harvest.arxiv.hold(wait)
                raise
    except FetchFailed as failed:
        next_step = after_failure(
            harvest.policy, claim.attempts + 1, failed.failure, harvest.draw()
        )
        async with session_scope(harvest.factory) as session:
            kept = await record_failure(session, claim, failed.failure.reason, next_step)
        logger.warning(
            "batch %d (%s): %s (%s)",
            claim.batch_id,
            claim.category,
            failed.failure.reason,
            type(next_step).__name__,
        )
    else:
        async with session_scope(harvest.factory) as session:
            kept = await record_announcement(
                session, claim, announced=announcement.announced, papers=announcement.papers
            )
    if not kept:
        logger.warning("batch %d: lease lost before the step was recorded", claim.batch_id)
    return True


async def run_harvester(harvest: Harvest, stop: asyncio.Event, idle_poll: timedelta) -> None:
    """Step until `stop` is set, resting for `idle_poll` whenever there is nothing to do.

    An unexpected error in one step is logged and the loop carries on: the
    batch's lease runs out and it is claimed again, so no step is lost.
    """
    while not stop.is_set():
        try:
            worked = await harvest_step(harvest)
        except Exception:
            logger.exception("harvest step failed")
            worked = False
        if not worked:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=idle_poll.total_seconds())
