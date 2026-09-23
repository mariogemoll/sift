"""The PDF download against a network that misbehaves in every way it can."""

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

import httpx
import pytest

from pdf_fake import pdf
from sift.core.retry import Retryable, Terminal
from sift.ingest.failures import FetchFailed
from sift.ingest.pdf import Limits, download_pdf, pdf_url

NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
PAPER = pdf("On Sifting")
LIMITS = Limits(max_bytes=64 * 1024, deadline=1.0)

type Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _pdf_response(
    body: bytes | AsyncIterator[bytes] = PAPER, headers: dict[str, str] | None = None
) -> httpx.Response:
    headers = {"content-type": "application/pdf", **(headers or {})}
    return httpx.Response(200, headers=headers, content=body)


async def _download(handler: Handler, limits: Limits = LIMITS) -> bytes:
    async with _client(handler) as client:
        return await download_pdf(client, "2609.26780", limits, now=lambda: NOW)


async def _failure(handler: Handler, limits: Limits = LIMITS) -> Retryable | Terminal:
    with pytest.raises(FetchFailed) as caught:
        await _download(handler, limits)
    return caught.value.failure


async def _chunks(*parts: bytes, pause: float = 0.0) -> AsyncIterator[bytes]:
    for part in parts:
        await asyncio.sleep(pause)
        yield part


def test_the_url_is_arxivs_pdf_link() -> None:
    assert pdf_url("2609.26780") == "https://arxiv.org/pdf/2609.26780"
    assert pdf_url("hep-th/9901001") == "https://arxiv.org/pdf/hep-th/9901001"


async def test_a_pdf_downloads_whole() -> None:
    assert await _download(lambda _: _pdf_response()) == PAPER


async def test_a_pdf_arriving_in_pieces_is_put_back_together() -> None:
    assert await _download(lambda _: _pdf_response(_chunks(PAPER[:100], PAPER[100:]))) == PAPER


async def test_redirects_to_a_versioned_url_are_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("v2"):
            return _pdf_response()
        return httpx.Response(301, headers={"location": f"{request.url}v2"})

    assert await _download(handler) == PAPER


async def test_the_parameters_ask_arxiv_for_the_pdf() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _pdf_response()

    await _download(handler)
    assert str(seen[0].url) == "https://arxiv.org/pdf/2609.26780"


@pytest.mark.parametrize("status", [404, 410])
async def test_a_missing_paper_is_terminal(status: int) -> None:
    assert isinstance(await _failure(lambda _: httpx.Response(status)), Terminal)


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_a_server_error_is_retryable(status: int) -> None:
    assert isinstance(await _failure(lambda _: httpx.Response(status)), Retryable)


async def test_a_503_passes_on_how_long_arxiv_asked_us_to_wait() -> None:
    failure = await _failure(lambda _: httpx.Response(503, headers={"retry-after": "30"}))
    assert failure == Retryable("HTTP 503 Service Unavailable", retry_after=30.0)


async def test_a_refused_connection_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    assert isinstance(await _failure(handler), Retryable)


async def test_a_connection_reset_halfway_through_the_body_is_retryable() -> None:
    async def reset() -> AsyncIterator[bytes]:
        yield PAPER[:50]
        raise httpx.ReadError("connection reset by peer")

    failure = await _failure(lambda _: _pdf_response(reset()))
    assert failure == Retryable("connection reset by peer")


async def test_an_html_page_instead_of_a_pdf_is_terminal() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html>")

    failure = await _failure(handler)
    assert failure == Terminal("expected a PDF, got text/html")


async def test_a_body_that_is_not_a_pdf_is_terminal_whatever_the_header_says() -> None:
    failure = await _failure(lambda _: _pdf_response(b"<html>not really</html>"))
    assert failure == Terminal("the body is not a PDF")


async def test_a_content_type_with_parameters_is_still_a_pdf() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "Application/PDF; qs=0.5"}, content=PAPER
        )

    assert await _download(handler) == PAPER


async def test_a_declared_length_over_the_cap_is_refused_before_reading() -> None:
    reads: list[int] = []

    async def body() -> AsyncIterator[bytes]:
        reads.append(1)
        yield PAPER

    limits = Limits(max_bytes=100, deadline=1.0)
    failure = await _failure(lambda _: _pdf_response(body(), {"content-length": "5000000"}), limits)
    assert failure == Terminal("the PDF is 5000000 bytes, over the 100-byte cap")
    assert reads == []


async def test_an_undeclared_body_is_cut_off_at_the_cap() -> None:
    sent: list[int] = []

    async def endless() -> AsyncIterator[bytes]:
        yield b"%PDF-"
        while True:
            sent.append(1)
            yield b"x" * 1024

    limits = Limits(max_bytes=10 * 1024, deadline=1.0)
    failure = await _failure(lambda _: _pdf_response(endless()), limits)
    assert failure == Terminal("the PDF exceeds the 10240-byte cap")
    assert len(sent) <= 11


async def test_a_server_that_never_answers_is_abandoned_at_the_deadline() -> None:
    async def hang(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(60)
        raise AssertionError("unreachable")

    limits = Limits(max_bytes=LIMITS.max_bytes, deadline=0.05)
    async with httpx.AsyncClient(transport=httpx.MockTransport(hang)) as client:
        with pytest.raises(FetchFailed) as caught:
            await asyncio.wait_for(download_pdf(client, "2609.26780", limits, now=lambda: NOW), 5)
    assert caught.value.failure == Retryable("no complete response within 0.05s")


async def test_a_trickling_body_is_abandoned_at_the_deadline() -> None:
    # Each chunk arrives well inside any per-read timeout; only the whole-download
    # deadline notices that the body as a whole is never going to finish.
    trickle = _chunks(PAPER[:10], *(b"x" for _ in range(1000)), pause=0.01)
    limits = Limits(max_bytes=LIMITS.max_bytes, deadline=0.1)
    started = asyncio.get_running_loop().time()
    failure = await _failure(lambda _: _pdf_response(trickle), limits)
    assert failure == Retryable("no complete response within 0.1s")
    assert asyncio.get_running_loop().time() - started < 1.0


def test_limits_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        Limits(max_bytes=0)
    with pytest.raises(ValueError, match="deadline"):
        Limits(deadline=0)
