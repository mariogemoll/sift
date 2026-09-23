"""One paper's full text: a paced download, then extraction.

The pacer is shared by everything fetching from the same host, so however many
papers are in flight, their downloads go out one at a time. Extraction happens
after the turn is given back — it does not touch the host, so it has no reason to
hold up the next download.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from sift.arxiv.extract import content_hash, extract_text
from sift.arxiv.failures import FetchFailed
from sift.arxiv.pacing import Pacer
from sift.arxiv.pdf import Limits, download_pdf
from sift.retry import Retryable


@dataclass(frozen=True, slots=True)
class Document:
    """A paper's extracted text. The PDF itself is not kept."""

    arxiv_id: str
    text: str
    content_hash: str
    pdf_bytes: int


async def fetch_document(
    client: httpx.AsyncClient,
    pacer: Pacer,
    arxiv_id: str,
    limits: Limits,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Document:
    """Download and extract one paper, or raise `FetchFailed`.

    A Retry-After on a refusal holds the pacer, so every paper waiting for the
    host waits it out, not only the one that was refused.
    """
    async with pacer.turn():
        try:
            pdf = await download_pdf(client, arxiv_id, limits, now=now)
        except FetchFailed as failed:
            match failed.failure:
                case Retryable(retry_after=float(wait)):
                    pacer.hold(wait)
            raise
    text = await asyncio.to_thread(extract_text, pdf)
    return Document(
        arxiv_id=arxiv_id, text=text, content_hash=content_hash(text), pdf_bytes=len(pdf)
    )
