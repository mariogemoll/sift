from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from arxiv_fake import Entry, FakeArxiv, feed
from sift.core.retry import Retryable, Terminal
from sift.ingest.announcements import (
    MalformedFeed,
    feed_url,
    fetch_announcement,
    parse_feed,
    valid_category,
)
from sift.ingest.failures import FetchFailed

# A real feed, captured from arXiv and cut down to one item of each announce type.
RECORDED = (Path(__file__).parent / "arxiv_feed.xml").read_bytes()


def test_a_recorded_feed_keeps_new_and_cross_listed_papers() -> None:
    announcement = parse_feed(RECORDED)

    assert announcement.announced == date(2026, 9, 23)
    assert [paper.arxiv_id for paper in announcement.papers] == ["2609.25194", "2609.25195"]
    first = announcement.papers[0]
    assert first.title == "Indirect tipping: a social attack surface in AI agent populations"
    assert first.authors[:2] == ("Ariel Flint", "Luca Maria Aiello")
    assert first.categories[:2] == ("cs.MA", "cs.AI")
    assert first.abstract.startswith("As generative AI agents are deployed at scale")
    assert first.published_at == datetime(2026, 9, 23, 4, tzinfo=UTC)


def test_revisions_are_not_new_papers() -> None:
    announcement = parse_feed(
        feed(Entry(id="1", kind="new"), Entry(id="2", kind="replace"), Entry(id="3", kind="cross"))
    )
    assert [paper.arxiv_id for paper in announcement.papers] == ["1", "3"]


def test_the_version_is_not_part_of_the_id() -> None:
    (paper,) = parse_feed(feed(Entry(id="2609.00001", version=3))).papers
    assert paper.arxiv_id == "2609.00001"


def test_line_breaks_inside_titles_collapse_to_spaces() -> None:
    (paper,) = parse_feed(feed(Entry(title="Attention\n   Is All\n  You Need"))).papers
    assert paper.title == "Attention Is All You Need"


def test_a_day_without_an_announcement_has_no_papers() -> None:
    announcement = parse_feed(feed())
    assert (announcement.announced, announcement.papers) == (date(2026, 9, 23), ())


@pytest.mark.parametrize(
    "body",
    [
        "not xml <",
        "<rss version='2.0'></rss>",
        "<rss version='2.0'><channel><pubDate>someday</pubDate></channel></rss>",
    ],
)
def test_an_unreadable_feed_is_malformed(body: str) -> None:
    with pytest.raises(MalformedFeed):
        parse_feed(body)


@pytest.mark.parametrize("category", ["cs.IR", "hep-th", "astro-ph.CO", "math"])
def test_categories_name_their_feed(category: str) -> None:
    assert feed_url(category) == f"https://rss.arxiv.org/rss/{category}"


@pytest.mark.parametrize("category", ["cs.IR+cs.AI", "cs.IR/../x", "", "CS.IR", "cs."])
def test_anything_that_could_name_another_feed_is_rejected(category: str) -> None:
    assert not valid_category(category)
    with pytest.raises(ValueError):
        feed_url(category)


async def fetch(arxiv: FakeArxiv, category: str = "cs.MA") -> object:
    async with httpx.AsyncClient(transport=httpx.MockTransport(arxiv.handle)) as client:
        return await fetch_announcement(client, category)


async def test_fetching_asks_for_the_category_feed_and_parses_it() -> None:
    arxiv = FakeArxiv(body=feed(Entry(id="2609.00001")))

    announcement = await fetch(arxiv)

    assert str(arxiv.requests[0].url) == "https://rss.arxiv.org/rss/cs.MA"
    assert announcement == parse_feed(feed(Entry(id="2609.00001")))


async def test_an_unknown_category_is_terminal() -> None:
    """arXiv answers 400, with a feed that names the error."""
    with pytest.raises(FetchFailed) as failed:
        await fetch(FakeArxiv(status=400, body=feed()), "zz.XX")
    assert failed.value.failure == Terminal("HTTP 400 Bad Request")


async def test_throttling_is_retryable_with_the_wait_asked_for() -> None:
    arxiv = FakeArxiv(status=503, headers={"retry-after": "30"})
    with pytest.raises(FetchFailed) as failed:
        await fetch(arxiv)
    assert failed.value.failure == Retryable("HTTP 503 Service Unavailable", retry_after=30.0)


async def test_a_garbled_feed_is_retryable() -> None:
    with pytest.raises(FetchFailed) as failed:
        await fetch(FakeArxiv(body="<rss"))
    assert isinstance(failed.value.failure, Retryable)


async def test_a_broken_connection_is_retryable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(refuse)) as client:
        with pytest.raises(FetchFailed) as failed:
            await fetch_announcement(client, "cs.MA")
    assert isinstance(failed.value.failure, Retryable)
