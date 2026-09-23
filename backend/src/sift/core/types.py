"""The domain vocabulary. Stdlib only, so importing it costs nothing."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Paper:
    """A document to be ranked, as the rest of the system talks about it."""

    arxiv_id: str
    title: str
    authors: tuple[str, ...]
    categories: tuple[str, ...]
    published_at: datetime
    abstract: str


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One window onto a longer sequence, plus the length of the whole."""

    items: tuple[T, ...]
    total: int
    limit: int
    offset: int


def empty_page[T](*, limit: int, offset: int) -> Page[T]:
    return Page(items=(), total=0, limit=limit, offset=offset)
