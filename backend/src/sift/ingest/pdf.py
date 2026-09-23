"""Downloading one paper's PDF, bounded in size and in time.

httpx's timeouts bound each operation — connecting, a single read — so a server
that sends a byte a second never trips them and holds the download open for as
long as it likes. The deadline here bounds the whole download instead, from the
first byte of the request to the last byte of the body.

The body is streamed and counted as it arrives, so an oversized or endless one is
cut off at the cap rather than read into memory first.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from sift.core.retry import Retryable, Terminal
from sift.ingest.failures import FetchFailed, from_error, from_status

PDF_URL = "https://arxiv.org/pdf/{}"
_PDF_MAGIC = b"%PDF-"


@dataclass(frozen=True, slots=True)
class Limits:
    """How much of a download is tolerated before it is abandoned."""

    max_bytes: int = 50 * 1024 * 1024
    deadline: float = 120.0
    """Seconds for the whole download, however the server paces it."""

    def __post_init__(self) -> None:
        if self.max_bytes <= 0:
            raise ValueError(f"max_bytes must be positive, got {self.max_bytes}")
        if self.deadline <= 0:
            raise ValueError(f"deadline must be positive, got {self.deadline}")


def pdf_url(arxiv_id: str) -> str:
    return PDF_URL.format(arxiv_id)


def _media_type(response: httpx.Response) -> str:
    value: str = response.headers.get("content-type", "")
    return value.partition(";")[0].strip().lower()


def _declared_length(response: httpx.Response) -> int | None:
    value: str = response.headers.get("content-length", "")
    return int(value) if value.isdigit() else None


async def _read_capped(response: httpx.Response, max_bytes: int) -> bytes:
    declared = _declared_length(response)
    if declared is not None and declared > max_bytes:
        raise FetchFailed(Terminal(f"the PDF is {declared} bytes, over the {max_bytes}-byte cap"))
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body += chunk
        if len(body) > max_bytes:
            raise FetchFailed(Terminal(f"the PDF exceeds the {max_bytes}-byte cap"))
    return bytes(body)


async def download_pdf(
    client: httpx.AsyncClient,
    arxiv_id: str,
    limits: Limits,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> bytes:
    """The PDF's bytes, or `FetchFailed` saying whether another attempt could help.

    The caller owns the client, and with it the transport and per-operation
    timeouts. `now` is the wall clock, for reading a Retry-After date.
    """
    try:
        async with (
            asyncio.timeout(limits.deadline),
            client.stream("GET", pdf_url(arxiv_id), follow_redirects=True) as response,
        ):
            if response.status_code != httpx.codes.OK:
                raise FetchFailed(from_status(response.status_code, response.headers, now()))
            media_type = _media_type(response)
            if media_type != "application/pdf":
                raise FetchFailed(Terminal(f"expected a PDF, got {media_type or 'no type'}"))
            body = await _read_capped(response, limits.max_bytes)
    except TimeoutError as error:
        raise FetchFailed(Retryable(f"no complete response within {limits.deadline:g}s")) from error
    except httpx.HTTPError as error:
        raise FetchFailed(from_error(error)) from error

    if not body.startswith(_PDF_MAGIC):
        raise FetchFailed(Terminal("the body is not a PDF"))
    return body
