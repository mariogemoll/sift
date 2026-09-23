"""The domain vocabulary. Stdlib only, so importing it costs nothing."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal


@dataclass(frozen=True, slots=True)
class Paper:
    """A document to be ranked, as the rest of the system talks about it."""

    arxiv_id: str
    title: str
    authors: tuple[str, ...]
    categories: tuple[str, ...]
    published_at: datetime
    abstract: str


BatchState = Literal["queued", "harvesting", "done", "failed"]


@dataclass(frozen=True, slots=True)
class Batch:
    """A harvest of one category over a window, and how far it has got.

    `added` counts papers new to the system; `items` counts every paper the batch
    has seen. arXiv does not say how many records a window holds in all, so there
    is no total to count towards: a batch is done when the last page arrives.
    """

    id: int
    category: str
    since: date
    until: date
    state: BatchState
    pages: int
    added: int
    items: int
    attempts: int
    last_error: str | None
    created_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One window onto a longer sequence, plus the length of the whole."""

    items: tuple[T, ...]
    total: int
    limit: int
    offset: int


def empty_page[T](*, limit: int, offset: int) -> Page[T]:
    return Page(items=(), total=0, limit=limit, offset=offset)
