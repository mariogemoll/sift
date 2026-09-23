"""The harvest worker, driven one step at a time against a fake arXiv and a real Postgres."""

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from arxiv_fake import Entry, FakeArxiv, oai_error, records
from sift.core.types import Paper
from sift.pipeline.harvest import Pacing, harvest_step, run_worker
from sift.storage.batches import claim_batch, record_page
from sift.storage.engine import session_scope

# What a worker that lost its lease would still try to write.
STALE_PAPER = Paper(
    arxiv_id="2609.99999",
    title="Written too late",
    authors=(),
    categories=("cs.IR",),
    published_at=datetime(2026, 9, 22, tzinfo=UTC),
    abstract="",
)

EAGER = Pacing(
    lease=timedelta(minutes=1), between_pages=timedelta(0), idle_poll=timedelta(seconds=0.05)
)


async def submit(client: AsyncClient, category: str = "cs.IR") -> int:
    response = await client.post("/batches", json={"category": category, "since": "2026-09-16"})
    assert response.status_code == 202
    batch_id: int = response.json()["id"]
    return batch_id


async def step(app: FastAPI, pacing: Pacing = EAGER) -> bool:
    return await harvest_step(app.state.session_factory, app.state.http, pacing)


async def batch(client: AsyncClient, batch_id: int) -> dict[str, object]:
    body: dict[str, object] = (await client.get(f"/batches/{batch_id}")).json()
    return body


async def test_a_one_page_batch_is_done_after_one_step(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv
) -> None:
    arxiv.body = records(Entry(id="2609.00001"), Entry(id="2609.00002"))
    batch_id = await submit(client)

    assert await step(app)
    after = await batch(client, batch_id)
    assert after["state"] == "done"
    assert (after["pages"], after["added"], after["items"]) == (1, 2, 2)
    assert after["finished_at"] is not None
    assert (await client.get("/papers")).json()["total"] == 2


async def test_nothing_to_claim_is_not_work(app: FastAPI, client: AsyncClient) -> None:
    assert not await step(app)


async def test_later_pages_are_asked_for_by_token_alone(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv
) -> None:
    arxiv.body = records(Entry(id="2609.00001"), token="p2")
    arxiv.pages = {"p2": records(Entry(id="2609.00002"), token="")}
    batch_id = await submit(client)

    await step(app)
    midway = await batch(client, batch_id)
    assert (midway["state"], midway["pages"], midway["items"]) == ("harvesting", 1, 1)

    await step(app)
    assert (await batch(client, batch_id))["state"] == "done"
    assert dict(arxiv.requests[1].url.params) == {"verb": "ListRecords", "resumptionToken": "p2"}
    assert (await batch(client, batch_id))["items"] == 2


async def test_the_next_page_waits_its_turn(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv
) -> None:
    arxiv.body = records(Entry(), token="p2")
    await submit(client)
    patient = Pacing(
        lease=timedelta(minutes=1), between_pages=timedelta(hours=1), idle_poll=EAGER.idle_poll
    )

    assert await step(app, patient)
    assert not await step(app, patient)
    assert len(arxiv.requests) == 1


async def test_an_outage_is_retried_later_and_then_recovers(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    arxiv.status = 503
    batch_id = await submit(client)

    await step(app)
    failed_once = await batch(client, batch_id)
    assert (failed_once["state"], failed_once["attempts"]) == ("harvesting", 1)
    assert "503" in str(failed_once["last_error"])
    assert not await step(app), "a batch in backoff is not due yet"

    await session.execute(text("update batches set not_before = now() - interval '1 second'"))
    await session.commit()
    arxiv.status, arxiv.body = 200, records(Entry())
    await step(app)
    recovered = await batch(client, batch_id)
    assert (recovered["state"], recovered["attempts"], recovered["last_error"]) == ("done", 0, None)


async def test_a_rejected_request_fails_the_batch_at_once(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv
) -> None:
    arxiv.body = oai_error("badArgument", "Set does not exist")
    batch_id = await submit(client, category="zz.XX")

    await step(app)
    after = await batch(client, batch_id)
    assert (after["state"], after["attempts"]) == ("failed", 1)
    assert "Set does not exist" in str(after["last_error"])
    assert after["finished_at"] is not None


async def test_the_last_attempt_fails_the_batch(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    arxiv.status = 503
    batch_id = await submit(client)
    await session.execute(text("update batches set attempts = 4"))
    await session.commit()

    await step(app)
    assert (await batch(client, batch_id))["state"] == "failed"


async def test_an_empty_window_is_done_with_nothing(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv
) -> None:
    arxiv.body = oai_error("noRecordsMatch", "nothing")
    batch_id = await submit(client)
    await step(app)
    after = await batch(client, batch_id)
    assert (after["state"], after["pages"], after["items"]) == ("done", 1, 0)


async def test_a_batch_held_by_a_dead_worker_is_reclaimed_once_its_lease_runs_out(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    arxiv.body = records(Entry(id="2609.00001"))
    batch_id = await submit(client)
    async with session_scope(app.state.session_factory) as dead_worker:
        stale = await claim_batch(dead_worker, timedelta(minutes=1))
    assert stale is not None

    assert not await step(app), "the lease is still live"

    await session.execute(text("update batches set lease_expires_at = now() - interval '1 second'"))
    await session.commit()
    assert await step(app)
    assert (await batch(client, batch_id))["state"] == "done"

    # The dead worker wakes up and tries to record its page: refused, nothing written.
    async with session_scope(app.state.session_factory) as late:
        kept = await record_page(
            late,
            stale,
            papers=(STALE_PAPER,),
            resumption_token="stale",
            next_page_after=timedelta(0),
        )
    assert not kept
    after = await batch(client, batch_id)
    assert (after["state"], after["pages"], after["items"]) == ("done", 1, 1)
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


async def test_the_same_window_twice_adds_no_papers_but_both_batches_have_items(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv
) -> None:
    arxiv.body = records(Entry(id="2609.00001"), Entry(id="2609.00002"))
    first, second = await submit(client), await submit(client)
    await step(app)
    await step(app)

    one, two = await batch(client, first), await batch(client, second)
    assert (one["added"], one["items"]) == (2, 2)
    assert (two["added"], two["items"]) == (0, 2)


async def test_the_worker_loop_runs_a_batch_to_completion_and_stops_when_told(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv
) -> None:
    arxiv.body = records(Entry(id="2609.00001"), token="p2")
    arxiv.pages = {"p2": records(Entry(id="2609.00002"), token="")}
    batch_id = await submit(client)

    stop = asyncio.Event()
    worker = asyncio.create_task(run_worker(app.state.session_factory, app.state.http, EAGER, stop))
    async with asyncio.timeout(5):
        while (await batch(client, batch_id))["state"] != "done":
            await asyncio.sleep(0.05)
    stop.set()
    async with asyncio.timeout(1):
        await worker
