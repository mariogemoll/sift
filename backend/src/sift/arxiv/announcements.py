"""New papers from arXiv's daily announcement of a category, as its RSS feed.

arXiv announces new submissions once a day, and each category's feed holds the
latest announcement: the papers new to the category that day, those cross-listed
into it, and replacements of older papers. Only the first two are new papers;
revisions are left out.

The feed is one small request per category. arXiv's OAI-PMH interface can list
any window of days instead, but its CDN refuses large listings to requests from
cloud networks, which is where this service runs.

Everything except `fetch_announcement` is pure, so parsing is tested without a
network.
"""

import re
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime

import httpx

from sift.arxiv.failures import FetchFailed, from_error, from_status
from sift.retry import Retryable
from sift.types import Paper

FEED_URL = "https://rss.arxiv.org/rss/{}"

_NS = {
    "arxiv": "http://arxiv.org/schemas/atom",
    "dc": "http://purl.org/dc/elements/1.1/",
}
# An archive, optionally with a subject class: `cs.IR`, `hep-th`, `astro-ph.CO`.
# Checked before it becomes part of a URL, where `+` would combine feeds.
_CATEGORY = re.compile(r"[a-z]+(?:-[a-z]+)*(?:\.[A-Za-z]+(?:-[A-Za-z]+)*)?")
_NEW = frozenset({"new", "cross"})
_GUID = re.compile(r"oai:arXiv\.org:(?P<id>.+?)(?:v\d+)?")
_WHITESPACE = re.compile(r"\s+")


class MalformedFeed(ValueError):
    """The feed could not be read as an announcement."""


@dataclass(frozen=True, slots=True)
class Announcement:
    """One day's announcement of one category: when, and the papers new in it.

    A day without an announcement — a weekend, a holiday — is an announcement
    with no papers, not an error.
    """

    announced: date
    papers: tuple[Paper, ...]


def valid_category(category: str) -> bool:
    return _CATEGORY.fullmatch(category) is not None


def feed_url(category: str) -> str:
    if not valid_category(category):
        raise ValueError(f"not an arXiv category: {category!r}")
    return FEED_URL.format(category)


def _clean(text: str | None) -> str:
    return _WHITESPACE.sub(" ", text or "").strip()


def _when(text: str | None, what: str) -> datetime:
    try:
        return parsedate_to_datetime(_clean(text))
    except (TypeError, ValueError) as error:
        raise MalformedFeed(f"unreadable {what}: {text!r}") from error


def _abstract(description: str) -> str:
    """The description is `arXiv:<id> Announce Type: <type> Abstract: <text>`."""
    _, marker, abstract = description.partition("Abstract:")
    return _clean(abstract if marker else description)


def _paper(item: ElementTree.Element) -> Paper:
    guid = _GUID.fullmatch(_clean(item.findtext("guid")))
    title = _clean(item.findtext("title"))
    if guid is None or not title:
        raise MalformedFeed(f"an item without an arXiv id or a title: {title!r}")
    creators = _clean(item.findtext("dc:creator", namespaces=_NS))
    return Paper(
        arxiv_id=guid.group("id"),
        title=title,
        authors=tuple(name.strip() for name in creators.split(",") if name.strip()),
        categories=tuple(_clean(category.text) for category in item.findall("category")),
        published_at=_when(item.findtext("pubDate"), "item date").astimezone(UTC),
        abstract=_abstract(item.findtext("description") or ""),
    )


def parse_feed(body: str | bytes) -> Announcement:
    """Read one category's feed into its announcement."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise MalformedFeed(f"the feed is not XML: {error}") from error
    channel = root.find("channel")
    if channel is None:
        raise MalformedFeed("the feed has no channel")
    announced = _when(channel.findtext("pubDate"), "announcement date").date()
    papers = tuple(
        _paper(item)
        for item in channel.findall("item")
        if _clean(item.findtext("arxiv:announce_type", namespaces=_NS)) in _NEW
    )
    return Announcement(announced=announced, papers=papers)


async def fetch_announcement(
    client: httpx.AsyncClient,
    category: str,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Announcement:
    """The category's latest announcement, or `FetchFailed` saying whether asking
    again could help. An unknown category is answered 400, which is terminal."""
    try:
        response = await client.get(feed_url(category))
    except httpx.HTTPError as error:
        raise FetchFailed(from_error(error)) from error
    if response.status_code != httpx.codes.OK:
        raise FetchFailed(from_status(response.status_code, response.headers, now()))
    try:
        return parse_feed(response.content)
    # A truncated or garbled body is the server's moment, not the category's.
    except MalformedFeed as error:
        raise FetchFailed(Retryable(str(error))) from error
