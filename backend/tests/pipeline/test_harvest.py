"""The harvest worker, driven one step at a time against a fake arXiv and a real Postgres."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import httpx
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from arxiv_fake import Entry, FakeArxiv, feed
from clock_fake import FakeClock
from sift.arxiv.pacing import Pacer
from sift.pipeline.harvest import Harvest, harvest_step, run_harvester
from sift.retry import RetryPolicy
from sift.storage.batches import claim_batch, record_announcement
from sift.storage.engine import session_scope
from sift.types import Paper

# What a worker that lost its lease would still try to write.
STALE_PAPER = Paper(
    arxiv_id="2609.99999",
    title="Written too late",
    authors=(),
    categories=("cs.RO",),
    published_at=datetime(2026, 9, 22, tzinfo=UTC),
    abstract="",
)


def harvesting(app: FastAPI, clock: FakeClock | None = None) -> Harvest:
    """The app's harvest, with a fixed draw and a pacer on a fake clock."""
    clock = clock or FakeClock()
    base: Harvest = app.state.harvest
    return replace(
        base,
        arxiv=Pacer(3.0, clock=clock, sleep=clock.sleep),
        policy=RetryPolicy(max_attempts=3),
        draw=lambda: 0.5,
    )


async def submit(client: AsyncClient) -> int:
    """Queue a batch for the test wishlist's one category."""
    response = await client.post("/batches")
    assert response.status_code == 202
    batch_id: int = response.json()[0]["id"]
    return batch_id


async def batch(client: AsyncClient, batch_id: int) -> dict[str, object]:
    body: dict[str, object] = (await client.get(f"/batches/{batch_id}")).json()
    return body


async def make_due(session: AsyncSession) -> None:
    await session.execute(text("update batches set not_before = now() - interval '1 second'"))
    await session.commit()


async def test_a_batch_is_done_after_one_step(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv
) -> None:
    arxiv.body = feed(Entry(id="2609.00001"), Entry(id="2609.00002"))
    batch_id = await submit(client)

    assert await harvest_step(harvesting(app))

    after = await batch(client, batch_id)
    assert (after["state"], after["announced"], after["added"], after["items"]) == (
        "done",
        "2026-09-23",
        2,
        2,
    )
    assert after["finished_at"] is not None
    assert str(arxiv.requests[0].url) == "https://rss.arxiv.org/rss/cs.RO"
    assert (await client.get("/papers")).json()["total"] == 2


async def test_nothing_to_claim_is_not_work(app: FastAPI, client: AsyncClient) -> None:
    assert not await harvest_step(harvesting(app))


async def test_a_day_without_an_announcement_is_done_with_nothing(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv
) -> None:
    arxiv.body = feed()
    batch_id = await submit(client)
    await harvest_step(harvesting(app))
    after = await batch(client, batch_id)
    assert (after["state"], after["status"], after["items"]) == ("done", "done", 0)


async def test_an_outage_is_retried_later_and_then_recovers(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    arxiv.status = 503
    batch_id = await submit(client)
    harvest = harvesting(app)

    await harvest_step(harvest)
    failed_once = await batch(client, batch_id)
    assert (failed_once["state"], failed_once["attempts"]) == ("harvesting", 1)
    assert failed_once["last_error"] == "HTTP 503 Service Unavailable"
    assert not await harvest_step(harvest), "a batch in backoff is not due yet"

    await make_due(session)
    arxiv.status, arxiv.body = 200, feed(Entry())
    await harvest_step(harvest)
    recovered = await batch(client, batch_id)
    assert (recovered["state"], recovered["attempts"], recovered["last_error"]) == ("done", 0, None)


async def test_a_retry_after_holds_the_pacer_downloads_share(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    arxiv.queued = [httpx.Response(503, headers={"retry-after": "90"})]
    arxiv.body = feed(Entry())
    await submit(client)
    clock = FakeClock()
    harvest = harvesting(app, clock)

    await harvest_step(harvest)
    waiting = await session.scalar(
        text("select not_before > now() + interval '80 seconds' from batches")
    )
    assert waiting, "Retry-After is a floor under the backoff"

    await make_due(session)
    await harvest_step(harvest)
    assert clock.slept == [90.0]


async def test_a_refused_category_fails_the_batch_at_once(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv
) -> None:
    arxiv.status, arxiv.body = 400, feed()
    batch_id = await submit(client)

    await harvest_step(harvesting(app))
    after = await batch(client, batch_id)
    assert (after["state"], after["status"], after["attempts"]) == ("failed", "failed", 1)
    assert after["last_error"] == "HTTP 400 Bad Request"
    assert after["finished_at"] is not None


async def test_the_last_attempt_fails_the_batch(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    arxiv.status = 503
    batch_id = await submit(client)
    harvest = harvesting(app)

    for _ in range(3):
        await harvest_step(harvest)
        await make_due(session)

    after = await batch(client, batch_id)
    assert (after["state"], after["attempts"]) == ("failed", 3)
    assert after["last_error"] == "HTTP 503 Service Unavailable (gave up after 3 attempts)"
    assert len(arxiv.requests) == 3


async def test_a_batch_held_by_a_dead_worker_is_reclaimed_once_its_lease_runs_out(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    arxiv.body = feed(Entry(id="2609.00001"))
    batch_id = await submit(client)
    harvest = harvesting(app)
    async with session_scope(app.state.session_factory) as dead_worker:
        stale = await claim_batch(dead_worker, timedelta(minutes=1))
    assert stale is not None

    assert not await harvest_step(harvest), "the lease is still live"

    await session.execute(text("update batches set lease_expires_at = now() - interval '1 second'"))
    await session.commit()
    assert await harvest_step(harvest)
    assert (await batch(client, batch_id))["state"] == "done"

    # The dead worker wakes up and tries to record what it fetched: refused.
    async with session_scope(app.state.session_factory) as late:
        kept = await record_announcement(
            late, stale, announced=date(2026, 9, 22), papers=(STALE_PAPER,)
        )
    assert not kept
    after = await batch(client, batch_id)
    assert (after["announced"], after["items"]) == ("2026-09-23", 1)
    assert (await client.get("/papers")).json()["total"] == 1


async def test_concurrent_claims_skip_a_locked_batch(app: FastAPI, client: AsyncClient) -> None:
    first_id = await submit(client)
    second_id = await submit(client)
    factory = app.state.session_factory

    async with factory() as one, factory() as two:
        held = await claim_batch(one, timedelta(minutes=1))
        other = await claim_batch(two, timedelta(minutes=1))
        assert held is not None and other is not None
        assert (held.batch_id, other.batch_id) == (first_id, second_id)

        async with factory() as three:
            assert await claim_batch(three, timedelta(minutes=1)) is None
        await one.rollback()
        await two.rollback()


async def test_the_same_announcement_twice_adds_no_papers_but_both_batches_have_items(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv
) -> None:
    arxiv.body = feed(Entry(id="2609.00001"), Entry(id="2609.00002"))
    first, second = await submit(client), await submit(client)
    harvest = harvesting(app)
    await harvest_step(harvest)
    await harvest_step(harvest)

    one, two = await batch(client, first), await batch(client, second)
    assert (one["added"], one["items"]) == (2, 2)
    assert (two["added"], two["items"]) == (0, 2)


async def test_the_worker_loop_runs_a_batch_to_completion_and_stops_when_told(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv
) -> None:
    arxiv.queued = [httpx.Response(503)]
    arxiv.body = feed(Entry(id="2609.00001"))
    batch_id = await submit(client)
    harvest = replace(harvesting(app), policy=RetryPolicy(base=0.01, cap=0.01))

    stop = asyncio.Event()
    worker = asyncio.create_task(run_harvester(harvest, stop, timedelta(seconds=0.05)))
    async with asyncio.timeout(5):
        while (await batch(client, batch_id))["state"] != "done":
            await asyncio.sleep(0.05)
    stop.set()
    async with asyncio.timeout(1):
        await worker
    assert (await batch(client, batch_id))["attempts"] == 0
