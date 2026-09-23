"""Paper metadata from arXiv's OAI-PMH interface, one request per call.

OAI-PMH is arXiv's channel for harvesting metadata in bulk. It selects records by
set (a category) and by datestamp — the day a record was last changed — so a
window catches papers that were revised in it as well as ones that are new.

A response holds one page of records plus a resumption token when there are
more; the next page is asked for by that token alone. Everything except
`fetch_page` is pure, so the requests and the parsing are tested without a
network.
"""

import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx

from sift.core.types import Paper

OAI_URL = "https://oaipmh.arxiv.org/oai"

_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "arxiv": "http://arxiv.org/OAI/arXiv/",
}
# An archive, optionally with a subject class: `cs.IR`, `hep-th`, `astro-ph.CO`.
# Checked before it becomes a set name, where anything else could name another set.
_CATEGORY = re.compile(r"([a-z]+(?:-[a-z]+)*)(?:\.([A-Za-z]+(?:-[A-Za-z]+)*))?")
# Archives arXiv files under its physics group; every other archive is a group of its own.
_PHYSICS = frozenset(
    {
        "astro-ph",
        "cond-mat",
        "gr-qc",
        "hep-ex",
        "hep-lat",
        "hep-ph",
        "hep-th",
        "math-ph",
        "nlin",
        "nucl-ex",
        "nucl-th",
        "physics",
        "quant-ph",
    }
)
_WHITESPACE = re.compile(r"\s+")


class ListingError(RuntimeError):
    """arXiv could not be asked, or answered with something unusable."""


class QueryRejected(ListingError):
    """arXiv understood the request and refused it, for instance for a set that does not exist."""


@dataclass(frozen=True, slots=True)
class Listing:
    """One page: its papers, and the token for the next page, None on the last.

    There is no total. arXiv's `completeListSize` turns out to describe the page
    in hand rather than the whole list, so it is not read.
    """

    papers: tuple[Paper, ...]
    resumption_token: str | None


def set_of(category: str) -> str:
    """The OAI-PMH set for a category: `cs.IR` -> `cs:cs:IR`, `hep-th` -> `physics:hep-th`."""
    match = _CATEGORY.fullmatch(category)
    if match is None:
        raise ValueError(f"not an arXiv category: {category!r}")
    archive, subject = match.groups()
    group = "physics" if archive in _PHYSICS else archive
    return f"{group}:{archive}" + (f":{subject}" if subject else "")


def valid_category(category: str) -> bool:
    return _CATEGORY.fullmatch(category) is not None


def first_page(category: str, since: date, until: date) -> dict[str, str]:
    """Records in `category` changed from `since` to `until`, inclusive, in arXiv's own format."""
    return {
        "verb": "ListRecords",
        "metadataPrefix": "arXiv",
        "set": set_of(category),
        "from": since.isoformat(),
        "until": until.isoformat(),
    }


def next_page(resumption_token: str) -> dict[str, str]:
    """The page after the one that handed out `resumption_token`. The token carries the query."""
    return {"verb": "ListRecords", "resumptionToken": resumption_token}


def _text(element: ElementTree.Element, path: str) -> str:
    found = element.find(path, _NS)
    if found is None or found.text is None:
        raise ListingError(f"record has no {path}")
    return _WHITESPACE.sub(" ", found.text).strip()


def _author(author: ElementTree.Element) -> str:
    parts = (
        author.findtext(f"arxiv:{field}", default="", namespaces=_NS).strip()
        for field in ("forenames", "keyname", "suffix")
    )
    return " ".join(part for part in parts if part)


def _paper(metadata: ElementTree.Element) -> Paper:
    created = date.fromisoformat(_text(metadata, "arxiv:created"))
    return Paper(
        arxiv_id=_text(metadata, "arxiv:id"),
        title=_text(metadata, "arxiv:title"),
        authors=tuple(
            _author(author) for author in metadata.findall("arxiv:authors/arxiv:author", _NS)
        ),
        categories=tuple(_text(metadata, "arxiv:categories").split()),
        published_at=datetime(created.year, created.month, created.day, tzinfo=UTC),
        abstract=_text(metadata, "arxiv:abstract"),
    )


def parse_response(body: str | bytes) -> Listing:
    """Read one ListRecords response. An empty window is an answer, not an error."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise ListingError(f"arXiv returned malformed XML: {error}") from error

    refusal = root.find("oai:error", _NS)
    if refusal is not None:
        code = refusal.get("code", "")
        if code == "noRecordsMatch":
            return Listing(papers=(), resumption_token=None)
        reason = _WHITESPACE.sub(" ", refusal.text or code).strip()
        raise QueryRejected(f"arXiv rejected the request: {reason}")

    records = root.find("oai:ListRecords", _NS)
    if records is None:
        raise ListingError("response has neither records nor an error")
    # Deleted records carry a header and no metadata; there is nothing to rank.
    papers = tuple(
        _paper(metadata) for metadata in records.findall("oai:record/oai:metadata/arxiv:arXiv", _NS)
    )
    # The last page of a longer list still carries the element, empty.
    token = records.find("oai:resumptionToken", _NS)
    following = (token.text or "").strip() if token is not None else ""
    return Listing(papers=papers, resumption_token=following or None)


async def fetch_page(client: httpx.AsyncClient, params: dict[str, str]) -> Listing:
    """One request, for `first_page(...)` or `next_page(...)`.

    The caller owns the client, and with it timeouts and transport.
    """
    try:
        response = await client.get(OAI_URL, params=params)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise ListingError(f"arXiv request failed: {error}") from error
    return parse_response(response.content)
