from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from arxiv_fake import Entry, FakeArxiv, oai_error, records
from sift.ingest.listing import (
    OAI_URL,
    ListingError,
    QueryRejected,
    fetch_listing,
    parse_response,
    request_params,
    set_of,
    valid_category,
)

# A real response, captured from arXiv and cut down to its first two records.
RECORDED = (Path(__file__).parent / "arxiv_response.xml").read_bytes()


def test_a_recorded_response_parses_into_papers() -> None:
    listing = parse_response(RECORDED)
    assert listing.total == 2
    assert [paper.arxiv_id for paper in listing.papers] == ["2510.27141", "2602.03422"]

    first = listing.papers[0]
    assert first.title == "Compass: General Filtered Search across Vector and Structured Data"
    assert first.authors[:3] == ("Chunxiao Ye", "Xiao Yan", "Eric Lo")
    assert first.categories == ("cs.DB", "cs.IR")
    assert first.published_at == datetime(2026, 9, 18, tzinfo=UTC)
    assert first.abstract != ""


def test_line_breaks_inside_titles_collapse_to_spaces() -> None:
    listing = parse_response(records(Entry(title="Attention\n   Is All\n  You Need")))
    assert listing.papers[0].title == "Attention Is All You Need"


def test_an_author_without_forenames_is_just_the_keyname() -> None:
    listing = parse_response(records(Entry(authors=(("Collaboration", ""),))))
    assert listing.papers[0].authors == ("Collaboration",)


def test_no_records_matching_is_an_empty_listing() -> None:
    listing = parse_response(oai_error("noRecordsMatch", "nothing in that window"))
    assert (listing.papers, listing.total) == ((), 0)


def test_a_resumption_token_reports_how_many_matched_in_all() -> None:
    assert parse_response(records(Entry(), total=2400)).total == 2400


def test_without_a_token_the_page_is_the_whole_listing() -> None:
    assert parse_response(records(Entry(id="1"), Entry(id="2"))).total == 2


def test_an_oai_error_is_a_rejection() -> None:
    with pytest.raises(QueryRejected, match="Set does not exist"):
        parse_response(oai_error("badArgument", "Set does not exist"))


def test_malformed_xml_is_a_listing_error() -> None:
    with pytest.raises(ListingError, match="malformed"):
        parse_response("<OAI-PMH><ListRecords>")


def test_a_response_with_neither_records_nor_error_is_a_listing_error() -> None:
    with pytest.raises(ListingError, match="neither"):
        parse_response(records().replace("ListRecords", "Identify"))


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("cs.IR", "cs:cs:IR"),
        ("math", "math:math"),
        ("q-bio.NC", "q-bio:q-bio:NC"),
        ("hep-th", "physics:hep-th"),
        ("astro-ph.CO", "physics:astro-ph:CO"),
    ],
)
def test_categories_map_to_their_sets(category: str, expected: str) -> None:
    assert valid_category(category)
    assert set_of(category) == expected


@pytest.mark.parametrize(
    "category", ["", "cs.IR&set=math", "cs:cs:IR", "CS.IR", "cs.", "cs IR", "cs.IR\n"]
)
def test_anything_that_could_name_another_set_is_rejected(category: str) -> None:
    assert not valid_category(category)
    with pytest.raises(ValueError, match="category"):
        set_of(category)


def test_the_request_names_the_set_and_the_window() -> None:
    params = request_params("cs.IR", date(2026, 9, 16), date(2026, 9, 23))
    assert params == {
        "verb": "ListRecords",
        "metadataPrefix": "arXiv",
        "set": "cs:cs:IR",
        "from": "2026-09-16",
        "until": "2026-09-23",
    }


async def test_fetching_sends_the_request_and_parses_the_answer() -> None:
    arxiv = FakeArxiv(body=records(Entry(id="2609.00001")))
    async with httpx.AsyncClient(transport=httpx.MockTransport(arxiv.handle)) as client:
        listing = await fetch_listing(client, "cs.IR", date(2026, 9, 1), date(2026, 9, 2))

    assert [paper.arxiv_id for paper in listing.papers] == ["2609.00001"]
    (request,) = arxiv.requests
    assert str(request.url).startswith(OAI_URL)
    assert request.url.params["set"] == "cs:cs:IR"


async def test_an_http_failure_is_a_listing_error() -> None:
    arxiv = FakeArxiv(status=503, body="try later")
    async with httpx.AsyncClient(transport=httpx.MockTransport(arxiv.handle)) as client:
        with pytest.raises(ListingError, match="503"):
            await fetch_listing(client, "cs.IR", date(2026, 9, 1), date(2026, 9, 2))
