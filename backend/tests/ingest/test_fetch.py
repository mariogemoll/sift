"""One paper's full text: a paced download, then extraction."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from clock_fake import FakeClock
from pdf_fake import pdf
from sift.core.retry import Retryable, Terminal
from sift.ingest.extract import content_hash
from sift.ingest.failures import FetchFailed
from sift.ingest.fetch import Document, fetch_document
from sift.ingest.pacing import Pacer
from sift.ingest.pdf import Limits

NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
LIMITS = Limits(max_bytes=64 * 1024, deadline=1.0)

type Handler = Callable[[httpx.Request], httpx.Response]


def _pacer(clock: FakeClock) -> Pacer:
    return Pacer(3.0, clock=clock, sleep=clock.sleep)


def _pdf(body: bytes) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "application/pdf"}, content=body)


async def _fetch(handler: Handler, pacer: Pacer, arxiv_id: str = "2609.26780") -> Document:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await fetch_document(client, pacer, arxiv_id, LIMITS, now=lambda: NOW)


async def test_a_document_carries_its_text_and_hash() -> None:
    body = pdf("On Sifting")
    document = await _fetch(lambda _: _pdf(body), _pacer(FakeClock()))
    assert document == Document(
        arxiv_id="2609.26780",
        text="On Sifting",
        content_hash=content_hash("On Sifting"),
        pdf_bytes=len(body),
    )


async def test_papers_fetched_together_still_go_one_every_interval() -> None:
    clock = FakeClock()
    pacer = _pacer(clock)
    started: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        started.append(clock.now)
        return _pdf(pdf("text"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await asyncio.gather(
            *(
                fetch_document(client, pacer, f"2609.0000{n}", LIMITS, now=lambda: NOW)
                for n in range(4)
            )
        )

    assert started == [0.0, 3.0, 6.0, 9.0]


async def test_a_retry_after_holds_back_every_other_paper_too() -> None:
    clock = FakeClock()
    pacer = _pacer(clock)
    with pytest.raises(FetchFailed) as caught:
        await _fetch(lambda _: httpx.Response(503, headers={"retry-after": "120"}), pacer)
    assert caught.value.failure == Retryable("HTTP 503 Service Unavailable", retry_after=120.0)

    await _fetch(lambda _: _pdf(pdf("text")), pacer, "2609.00002")
    assert clock.slept == [120.0]


async def test_extraction_failures_come_out_as_fetch_failures() -> None:
    with pytest.raises(FetchFailed) as caught:
        await _fetch(lambda _: _pdf(pdf("")), _pacer(FakeClock()))
    assert caught.value.failure == Terminal("the PDF has no text layer")
