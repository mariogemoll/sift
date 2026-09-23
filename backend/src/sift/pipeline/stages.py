"""The stages a harvested paper goes through, each run by its own workers.

    screen ──passes──▶ fetch ──▶ judge ──▶ done
       └──passed over───────────────────▶ done
    any stage ──attempts run out, or a terminal failure──▶ dead

A step claims one item waiting for a stage, does the stage's work with no
transaction open, then records the outcome in one transaction guarded by the
item's lease. Nothing is held in memory between steps, so a worker killed at any
point loses only the step in hand: the lease runs out and another worker takes
the item from where its last recorded stage left it.

The stages are limited separately, because their limits mean different things.
The screen and the judge are bounded by how many workers run them, which is a
budget for the model. The fetch shares one `Pacer` for arXiv, which lets one
request go at a time and no sooner than the interval after the last one ended,
however many fetch workers are waiting on it.

Every stage is safe to repeat. Answers are cached under a hash of everything the
model was given, text is stored once per paper, and a verdict is written, not
appended, so an item done twice — two overlapping batches, or a worker that died
after asking but before recording — costs a lookup rather than a second answer.
"""

import asyncio
import contextlib
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sift.arxiv.failures import FetchFailed
from sift.arxiv.fetch import fetch_document
from sift.arxiv.pacing import Pacer
from sift.arxiv.pdf import Limits
from sift.judging import Ask, Asker, AskFailed, ask_for, scoring, screen_ask_for
from sift.judging.cache import key_for
from sift.judging.judgments import Document, Judgments, Profile, Verdict
from sift.judging.text import for_judging
from sift.retry import Failure, Retryable, RetryPolicy, after_failure
from sift.storage.engine import session_scope
from sift.storage.items import ItemClaim, advance_item, claim_item, record_item_failure
from sift.storage.judgments import cached_judgments, store_judgments
from sift.storage.texts import get_text, has_text, put_text
from sift.storage.verdicts import put_verdict
from sift.types import ItemState, Stage

logger = logging.getLogger(__name__)

type Record = Callable[[AsyncSession], Awaitable[None]]


async def _nothing(_: AsyncSession) -> None:
    return None


@dataclass(frozen=True, slots=True)
class Advance:
    """The stage succeeded: move on to `to`, writing `record` in the same transaction."""

    to: ItemState
    record: Record = _nothing


@dataclass(frozen=True, slots=True)
class Failed:
    failure: Failure


type Outcome = Advance | Failed


@dataclass(frozen=True, slots=True)
class Work:
    """Everything a stage worker needs. One per process, shared by every worker in it."""

    factory: async_sessionmaker[AsyncSession]
    http: httpx.AsyncClient
    arxiv: Pacer
    limits: Limits
    asker: Asker
    profile: Profile
    max_chars: int
    """How much of a paper's text, references removed, the full judgment reads."""
    lease: timedelta
    """Must outlast one stage's work, including the wait for the arXiv pacer."""
    policy: RetryPolicy
    download: bool = True
    """Fetch PDFs from arXiv. Off, the fetch stage passes papers straight on and
    the judge reads the abstract in place of the text, storing nothing — for runs
    whose answers do not depend on the text, where a download would be waste."""
    draw: Callable[[], float] = random.random


@dataclass(frozen=True, slots=True)
class _Answered:
    judgments: Judgments
    key: str
    fresh: bool


async def _answers(work: Work, ask: Ask) -> _Answered:
    """Cached answers when the same question was asked of the same state before."""
    key = key_for(ask.state, ask.asked, model=work.asker.model)
    async with session_scope(work.factory) as session:
        cached = await cached_judgments(session, key)
    if cached is not None:
        return _Answered(cached, key, fresh=False)
    (judgments,) = await work.asker([ask])
    return _Answered(judgments, key, fresh=True)


def _recording(work: Work, claim: ItemClaim, answered: _Answered, verdict: Verdict) -> Record:
    async def record(session: AsyncSession) -> None:
        if answered.fresh:
            await store_judgments(session, answered.key, work.asker.model, answered.judgments)
        await put_verdict(session, claim.paper_id, work.profile.name, verdict, answered.key)

    return record


async def screen(work: Work, claim: ItemClaim) -> Outcome:
    """Judge fit and dealbreakers from the title and abstract; only a pass is fetched."""
    answered = await _answers(work, screen_ask_for(claim.title, claim.abstract, work.profile))
    verdict = scoring.screen(claim.arxiv_id, answered.judgments, work.profile)
    return Advance(
        "fetch" if scoring.passes_screen(verdict, work.profile) else "done",
        _recording(work, claim, answered, verdict),
    )


async def fetch(work: Work, claim: ItemClaim) -> Outcome:
    """Download and extract the paper, unless its text is already stored."""
    if not work.download:
        return Advance("judge")
    async with session_scope(work.factory) as session:
        if await has_text(session, claim.paper_id):
            return Advance("judge")
    document = await fetch_document(work.http, work.arxiv, claim.arxiv_id, work.limits)

    async def record(session: AsyncSession) -> None:
        await put_text(
            session,
            claim.paper_id,
            text=document.text,
            content_hash=document.content_hash,
            pdf_bytes=document.pdf_bytes,
        )

    return Advance("judge", record)


async def judge(work: Work, claim: ItemClaim) -> Outcome:
    """Judge merit and fit from the text, with the reference list left out."""
    async with session_scope(work.factory) as session:
        text = await get_text(session, claim.paper_id)
    if text is None and not work.download:
        text = f"{claim.title}\n\n{claim.abstract}"
    if text is None:
        # Nothing deletes text, so this is a paper that skipped the fetch somehow.
        return Advance("fetch")
    document = Document(claim.arxiv_id, for_judging(text, work.max_chars))
    answered = await _answers(work, ask_for(document, work.profile))
    verdict = scoring.evaluate(claim.arxiv_id, answered.judgments, work.profile)
    return Advance("done", _recording(work, claim, answered, verdict))


STAGES: dict[Stage, Callable[[Work, ItemClaim], Awaitable[Outcome]]] = {
    "screen": screen,
    "fetch": fetch,
    "judge": judge,
}


async def _attempt(work: Work, claim: ItemClaim) -> Outcome:
    try:
        return await STAGES[claim.stage](work, claim)
    except (AskFailed, FetchFailed) as error:
        return Failed(error.failure)
    # Anything else is a bug or a surprise. It is counted as an attempt like any
    # other failure, so an item that trips one dies with the error recorded rather
    # than cycling through lease expiries forever.
    except Exception as error:
        logger.exception("%s of item %d failed unexpectedly", claim.stage, claim.item_id)
        return Failed(Retryable(f"unexpected: {error!r}"))


async def step(work: Work, stage: Stage) -> bool:
    """Take one item through `stage`. False when nothing was waiting for it."""
    async with session_scope(work.factory) as session:
        claim = await claim_item(session, stage, work.lease)
    if claim is None:
        return False

    outcome = await _attempt(work, claim)
    async with session_scope(work.factory) as session:
        match outcome:
            case Advance(to, record):
                kept = await advance_item(session, claim, to)
                if kept:
                    await record(session)
            case Failed(failure):
                next_step = after_failure(work.policy, claim.attempts + 1, failure, work.draw())
                kept = await record_item_failure(session, claim, failure.reason, next_step)
                logger.warning(
                    "%s of %s failed: %s (%s)",
                    stage,
                    claim.arxiv_id,
                    failure.reason,
                    type(next_step).__name__,
                )
    if not kept:
        logger.warning("item %d: lease lost before %s was recorded", claim.item_id, stage)
    return True


async def run_stage(work: Work, stage: Stage, stop: asyncio.Event, idle_poll: timedelta) -> None:
    """Step until `stop` is set, resting for `idle_poll` whenever nothing is waiting."""
    while not stop.is_set():
        try:
            worked = await step(work, stage)
        except Exception:
            logger.exception("%s step failed", stage)
            worked = False
        if not worked:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=idle_poll.total_seconds())
