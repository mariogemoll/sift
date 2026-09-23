"""The item stages, driven one step at a time against fakes and a real Postgres.

Every failure here is injected on purpose: a flaky server, a paper that is gone,
a model that throttles, a worker that dies holding an item. What is checked is
where the item ends up, what it remembers, and what was asked of whom how often.
"""

from dataclasses import dataclass, field, replace

import httpx
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from arxiv_fake import Entry, FakeArxiv, feed
from asker_fake import ScriptedAsker
from clock_fake import FakeClock
from pdf_fake import pdf
from sift.arxiv.pacing import Pacer
from sift.pipeline.harvest import harvest_step
from sift.pipeline.stages import Work, step
from sift.retry import Retryable, RetryPolicy, Terminal
from sift.settings import Settings, downloads
from sift.storage.engine import session_scope
from sift.storage.items import advance_item, claim_item
from sift.storage.models import BatchItem, PaperText, Verdict
from sift.types import Stage

PROMISING = Entry(id="2609.00001", title="Robot grasping", abstract="We study robotics.")
DULL = Entry(id="2609.00002", title="Tax law", abstract="A survey of tax codes.")
RETRACTED = Entry(id="2609.00003", title="Robot fraud", abstract="Retracted robotics.")


@dataclass
class FakePdfs:
    """arxiv.org/pdf, answering each id from `responses` and remembering the asks.

    A response left in `queued` for an id is used once, before `responses`, so a
    test can lay out a failure followed by a success.
    """

    responses: dict[str, httpx.Response] = field(default_factory=dict)
    queued: dict[str, list[httpx.Response]] = field(default_factory=dict)
    requests: list[str] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        arxiv_id = request.url.path.removeprefix("/pdf/")
        self.requests.append(arxiv_id)
        if self.queued.get(arxiv_id):
            return self.queued[arxiv_id].pop(0)
        return self.responses.get(arxiv_id, httpx.Response(404))


def a_pdf(*pages: str) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "application/pdf"}, content=pdf(*pages))


def working(
    app: FastAPI, asker: ScriptedAsker, pdfs: FakePdfs, clock: FakeClock | None = None
) -> Work:
    """The app's work, with fakes for the model and the PDF host, and a pacer on a
    fake clock, so a Retry-After holds the pacer without holding up the test."""
    clock = clock or FakeClock()
    base: Work = app.state.work
    return replace(
        base,
        asker=asker,
        http=httpx.AsyncClient(transport=httpx.MockTransport(pdfs.handle)),
        arxiv=Pacer(3.0, clock=clock, sleep=clock.sleep),
        policy=RetryPolicy(max_attempts=3),
        draw=lambda: 0.5,
        download=True,
    )


async def harvested(app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, *entries: Entry) -> int:
    arxiv.body = feed(*entries)
    response = await client.post("/batches")
    assert response.status_code == 202
    assert await harvest_step(app.state.harvest)
    batch_id: int = response.json()[0]["id"]
    return batch_id


async def run_all(work: Work, *stages: Stage) -> None:
    """Step each stage until nothing is waiting for any of them."""
    stages = stages or ("screen", "fetch", "judge")
    while any([await step(work, stage) for stage in stages]):
        pass


async def items(session: AsyncSession) -> dict[str, BatchItem]:
    rows = await session.execute(
        text("select p.arxiv_id, i.id from batch_items i join papers p on p.id = i.paper_id")
    )
    ids = dict(rows.tuples().all())
    found = (
        await session.scalars(select(BatchItem).execution_options(populate_existing=True))
    ).all()
    by_id = {item.id: item for item in found}
    return {arxiv_id: by_id[item_id] for arxiv_id, item_id in ids.items()}


async def verdicts(session: AsyncSession) -> dict[int, Verdict]:
    found = await session.scalars(select(Verdict).execution_options(populate_existing=True))
    return {verdict.paper_id: verdict for verdict in found.all()}


async def make_due(session: AsyncSession) -> None:
    """Skip a backoff: every waiting item is due now."""
    await session.execute(update(BatchItem).values(not_before=None))
    await session.commit()


async def test_a_promising_paper_is_screened_fetched_and_judged(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    await harvested(app, client, arxiv, PROMISING)
    pdfs = FakePdfs({PROMISING.id: a_pdf("Robotics, all the way down.")})
    asker = ScriptedAsker(fits={"obot": 0.9})
    work = working(app, asker, pdfs)

    await run_all(work)

    (item,) = (await items(session)).values()
    assert (item.state, item.attempts, item.last_error) == ("done", 0, None)
    (verdict,) = (await verdicts(session)).values()
    assert (verdict.stage, verdict.eligible, verdict.profile) == ("full", True, "test")
    assert verdict.merit is not None
    assert pdfs.requests == [PROMISING.id]
    stored = await session.scalar(select(PaperText.text))
    assert stored == "Robotics, all the way down."
    # One screen of the abstract, one judgment of the text.
    assert [ask.state["document"] for ask in asker.asks] == [
        "Robot grasping\n\nWe study robotics.",
        "Robotics, all the way down.",
    ]


async def test_a_paper_that_fails_the_screen_is_never_downloaded(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    await harvested(app, client, arxiv, DULL)
    pdfs = FakePdfs()
    work = working(app, ScriptedAsker(fits={"tax": 0.1}), pdfs)

    await run_all(work)

    (item,) = (await items(session)).values()
    assert item.state == "done"
    (verdict,) = (await verdicts(session)).values()
    assert (verdict.stage, verdict.eligible, verdict.merit) == ("screen", True, None)
    assert pdfs.requests == []


async def test_a_dealbreaker_blocks_at_the_screen_whatever_the_fit(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    await harvested(app, client, arxiv, RETRACTED)
    pdfs = FakePdfs()
    work = working(app, ScriptedAsker(fits={"obot": 1.0}, blocks={"etracted": 0.95}), pdfs)

    await run_all(work)

    (verdict,) = (await verdicts(session)).values()
    assert (verdict.stage, verdict.eligible, verdict.blocked_by) == (
        "screen",
        False,
        ["retracted"],
    )
    assert pdfs.requests == []


async def test_a_paper_in_two_batches_is_asked_about_and_downloaded_once(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    pdfs = FakePdfs({PROMISING.id: a_pdf("Robotics.")})
    asker = ScriptedAsker(fits={"obot": 0.9})
    work = working(app, asker, pdfs)

    await harvested(app, client, arxiv, PROMISING)
    await run_all(work)
    await harvested(app, client, arxiv, PROMISING)
    await run_all(work)

    assert [item.state for item in (await session.scalars(select(BatchItem))).all()] == [
        "done",
        "done",
    ]
    assert pdfs.requests == [PROMISING.id]
    assert len(asker.asks) == 2
    (verdict,) = (await verdicts(session)).values()
    assert verdict.stage == "full"


async def test_a_flaky_server_is_retried_after_a_backoff_and_then_succeeds(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    await harvested(app, client, arxiv, PROMISING)
    pdfs = FakePdfs(
        {PROMISING.id: a_pdf("Robotics.")},
        queued={PROMISING.id: [httpx.Response(503, headers={"retry-after": "120"})]},
    )
    clock = FakeClock()
    work = working(app, ScriptedAsker(fits={"obot": 0.9}), pdfs, clock)

    await run_all(work)

    item = (await items(session))[PROMISING.id]
    assert (item.state, item.attempts) == ("fetch", 1)
    assert item.last_error == "HTTP 503 Service Unavailable"
    waiting = await session.scalar(
        text("select not_before > now() + interval '100 seconds' from batch_items")
    )
    assert waiting, "Retry-After is a floor under the backoff"

    await make_due(session)
    await run_all(work)

    item = (await items(session))[PROMISING.id]
    assert (item.state, item.attempts, item.last_error) == ("done", 0, None)
    assert pdfs.requests == [PROMISING.id, PROMISING.id]
    assert clock.slept == [120.0], "the whole host was held, not only the refused request"


async def test_a_missing_paper_dies_at_once_without_spending_attempts(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    await harvested(app, client, arxiv, PROMISING)
    pdfs = FakePdfs()  # every id answers 404
    work = working(app, ScriptedAsker(fits={"obot": 0.9}), pdfs)

    await run_all(work)

    item = (await items(session))[PROMISING.id]
    assert (item.state, item.attempts) == ("dead", 1)
    assert item.last_error == "HTTP 404 Not Found"
    assert pdfs.requests == [PROMISING.id]


async def test_a_failure_that_keeps_happening_dies_when_attempts_run_out(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    await harvested(app, client, arxiv, PROMISING)
    pdfs = FakePdfs({PROMISING.id: httpx.Response(500)})
    work = working(app, ScriptedAsker(fits={"obot": 0.9}), pdfs)

    for _ in range(3):
        await run_all(work)
        await make_due(session)

    item = (await items(session))[PROMISING.id]
    assert (item.state, item.attempts) == ("dead", 3)
    assert item.last_error == "HTTP 500 Internal Server Error (gave up after 3 attempts)"
    assert len(pdfs.requests) == 3


async def test_a_throttling_model_is_waited_out_and_nothing_is_recorded_meanwhile(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    await harvested(app, client, arxiv, PROMISING)
    asker = ScriptedAsker(
        fits={"obot": 0.9}, failures=[Retryable("TypeSafe: 429", retry_after=30.0)]
    )
    work = working(app, asker, FakePdfs({PROMISING.id: a_pdf("Robotics.")}))

    await run_all(work)

    item = (await items(session))[PROMISING.id]
    assert (item.state, item.attempts, item.last_error) == ("screen", 1, "TypeSafe: 429")
    assert await verdicts(session) == {}

    await make_due(session)
    await run_all(work)
    assert (await items(session))[PROMISING.id].state == "done"


async def test_a_refused_model_request_is_terminal(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    await harvested(app, client, arxiv, PROMISING)
    asker = ScriptedAsker(failures=[Terminal("TypeSafe: 422 malformed")])
    work = working(app, asker, FakePdfs())

    await run_all(work)

    item = (await items(session))[PROMISING.id]
    assert (item.state, item.last_error) == ("dead", "TypeSafe: 422 malformed")


async def test_an_unexpected_error_is_counted_rather_than_retried_forever(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    await harvested(app, client, arxiv, PROMISING)

    class Broken(ScriptedAsker):
        async def __call__(self, asks: object) -> list[object]:  # type: ignore[override]
            raise KeyError("a bug")

    work = working(app, Broken(), FakePdfs())

    await run_all(work)

    item = (await items(session))[PROMISING.id]
    assert (item.state, item.attempts) == ("screen", 1)
    assert item.last_error == "unexpected: KeyError('a bug')"


async def test_a_worker_that_dies_holding_an_item_hands_it_on_when_the_lease_runs_out(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    await harvested(app, client, arxiv, PROMISING)
    work = working(app, ScriptedAsker(fits={"obot": 0.9}), FakePdfs({PROMISING.id: a_pdf("R")}))

    async with session_scope(work.factory) as claiming:
        dead_worker = await claim_item(claiming, "screen", work.lease)
    assert dead_worker is not None
    assert not await step(work, "screen"), "a held item is not claimed twice"

    await session.execute(update(BatchItem).values(lease_expires_at=text("now()")))
    await session.commit()
    await run_all(work)
    assert (await items(session))[PROMISING.id].state == "done"

    async with session_scope(work.factory) as late:
        assert not await advance_item(late, dead_worker, "fetch"), "its late write is refused"
    assert (await items(session))[PROMISING.id].state == "done"


async def test_ranking_puts_papers_read_in_full_first(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    await harvested(app, client, arxiv, DULL, RETRACTED, PROMISING)
    asker = ScriptedAsker(fits={"obot": 0.9, "tax": 0.2}, blocks={"etracted": 0.95})
    await run_all(working(app, asker, FakePdfs({PROMISING.id: a_pdf("Robotics.")})))

    body = (await client.get("/papers")).json()

    ranked = [(item["paper"]["arxiv_id"], item["verdict"]["stage"]) for item in body["items"]]
    assert ranked == [(PROMISING.id, "full"), (DULL.id, "screen"), (RETRACTED.id, "screen")]
    assert body["items"][2]["verdict"]["blocked_by"] == ["retracted"]


async def test_batch_progress_counts_items_by_state(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv
) -> None:
    batch_id = await harvested(app, client, arxiv, DULL, PROMISING)
    await run_all(working(app, ScriptedAsker(fits={"tax": 0.1}), FakePdfs()), "screen")

    body = (await client.get(f"/batches/{batch_id}")).json()

    assert body["progress"] == {"done": 1, "fetch": 1}
    assert body["items"] == 2
    assert (body["state"], body["status"]) == ("done", "processing")


async def test_without_downloads_nothing_is_fetched_or_stored(
    app: FastAPI, client: AsyncClient, arxiv: FakeArxiv, session: AsyncSession
) -> None:
    """The judge reads the abstract instead, and no stand-in text is kept that a
    later run with downloads on would mistake for the paper."""
    await harvested(app, client, arxiv, PROMISING)
    pdfs = FakePdfs({PROMISING.id: a_pdf("Robotics.")})
    asker = ScriptedAsker(fits={"obot": 0.9})
    await run_all(replace(working(app, asker, pdfs), download=False))

    assert (await items(session))[PROMISING.id].state == "done"
    assert pdfs.requests == []
    assert await session.scalar(select(PaperText.paper_id)) is None
    assert asker.asks[-1].state["document"] == "Robot grasping\n\nWe study robotics."


def test_downloads_follow_the_asker_unless_set(settings: Settings) -> None:
    assert not downloads(settings.model_copy(update={"asker": "fake"}))
    assert downloads(settings.model_copy(update={"asker": "typesafe"}))
    assert downloads(settings.model_copy(update={"asker": "fake", "download": True}))
