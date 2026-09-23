"""A stand-in for arXiv's announcement feeds, and feeds shaped like the ones it serves."""

from dataclasses import dataclass, field
from html import escape

import httpx


@dataclass
class FakeArxiv:
    """Answers every feed request with `status` and `body`, and remembers what it was asked.

    A response left in `queued` is used once, before `status` and `body`, so a
    test can lay out failures followed by a success.
    """

    status: int = 200
    body: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    queued: list[httpx.Response] = field(default_factory=list)
    requests: list[httpx.Request] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.queued:
            return self.queued.pop(0)
        return httpx.Response(self.status, text=self.body, headers=self.headers)


@dataclass(frozen=True)
class Entry:
    """One paper as an announcement feed describes it."""

    id: str = "2609.26780"
    version: int = 1
    title: str = "A Paper"
    abstract: str = "What it is about."
    authors: tuple[str, ...] = ("A. Author",)
    categories: tuple[str, ...] = ("cs.IR",)
    kind: str = "new"


ANNOUNCED = "Wed, 23 Sep 2026 00:00:00 -0400"


def _item(entry: Entry) -> str:
    categories = "".join(f"<category>{escape(c)}</category>" for c in entry.categories)
    return (
        f"<item><title>{escape(entry.title)}</title>"
        f"<link>https://arxiv.org/abs/{entry.id}</link>"
        f"<description>arXiv:{entry.id}v{entry.version} Announce Type: {entry.kind} \n"
        f"Abstract: {escape(entry.abstract)}</description>"
        f'<guid isPermaLink="false">oai:arXiv.org:{entry.id}v{entry.version}</guid>'
        f"{categories}<pubDate>{ANNOUNCED}</pubDate>"
        f"<arxiv:announce_type>{entry.kind}</arxiv:announce_type>"
        f"<dc:creator>{escape(', '.join(entry.authors))}</dc:creator></item>"
    )


def feed(*entries: Entry, announced: str = ANNOUNCED) -> str:
    """One category's announcement feed."""
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        '<rss xmlns:arxiv="http://arxiv.org/schemas/atom" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0"><channel>'
        f"<title>updates on arXiv.org</title><pubDate>{announced}</pubDate>"
        f"{''.join(_item(entry) for entry in entries)}</channel></rss>"
    )
