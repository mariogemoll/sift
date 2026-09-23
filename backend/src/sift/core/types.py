"""The domain vocabulary. Stdlib only, so importing it costs nothing."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from .judgments import Verdict


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
class Assessed:
    """A paper and where it stands against a wishlist; None until it is screened."""

    paper: Paper
    verdict: Verdict | None


Order = Literal["rank", "newest"]


BatchState = Literal["queued", "harvesting", "done", "failed"]

ItemState = Literal["screen", "fetch", "judge", "done", "dead"]
"""The stage an item waits for, or how it ended."""

Stage = Literal["screen", "fetch", "judge"]
"""The item states a worker can claim."""

BatchStatus = Literal["queued", "harvesting", "processing", "done", "failed"]
"""Where a batch stands as a whole: its harvest, then its papers going through
the stages. A harvest can be done while its papers are still being judged."""


def batch_status(state: BatchState, progress: Mapping[ItemState, int]) -> BatchStatus:
    if state != "done":
        return state
    waiting = sum(progress.get(stage, 0) for stage in ("screen", "fetch", "judge"))
    return "processing" if waiting else "done"


@dataclass(frozen=True, slots=True)
class Batch:
    """One category's daily announcement, and how far its papers have got.

    `announced` is the day arXiv announced the papers, None until fetched.
    `added` counts papers new to the system; `items` counts every paper the batch
    holds, and `progress` how many of them wait for or ended in each state.
    """

    id: int
    category: str
    state: BatchState
    announced: date | None
    added: int
    items: int
    progress: Mapping[ItemState, int]
    status: BatchStatus
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
