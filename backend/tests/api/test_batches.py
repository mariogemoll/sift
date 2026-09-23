from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from arxiv_fake import Entry, FakeArxiv, oai_error, records

TWO_PAPERS = records(
    Entry(id="2609.00001", title="First", created="2026-09-20"),
    Entry(id="2609.00002", title="Second", created="2026-09-21"),
    total=40,
)


async def test_a_batch_stores_the_listing_and_reports_counts(
    client: AsyncClient, arxiv: FakeArxiv
) -> None:
    arxiv.body = TWO_PAPERS
    response = await client.post("/batches", json={"category": "cs.IR", "since": "2026-09-16"})

    assert response.status_code == 200
    body = response.json()
    assert (body["matched"], body["fetched"], body["added"]) == (40, 2, 2)
    assert body["until"] == datetime.now(UTC).date().isoformat()

    papers = (await client.get("/papers")).json()
    assert [item["title"] for item in papers["items"]] == ["Second", "First"]


async def test_the_same_window_twice_adds_nothing_the_second_time(
    client: AsyncClient, arxiv: FakeArxiv
) -> None:
    arxiv.body = TWO_PAPERS
    request = {"category": "cs.IR", "since": "2026-09-16"}
    await client.post("/batches", json=request)
    second = (await client.post("/batches", json=request)).json()

    assert (second["fetched"], second["added"]) == (2, 0)
    assert (await client.get("/papers")).json()["total"] == 2


async def test_the_window_reaches_arxiv(client: AsyncClient, arxiv: FakeArxiv) -> None:
    arxiv.body = records()
    await client.post("/batches", json={"category": "hep-th", "since": "2026-09-16"})
    params = arxiv.requests[0].url.params
    assert (params["set"], params["from"]) == ("physics:hep-th", "2026-09-16")
    assert params["until"] == datetime.now(UTC).date().isoformat()


async def test_a_set_arxiv_does_not_know_is_unprocessable(
    client: AsyncClient, arxiv: FakeArxiv
) -> None:
    arxiv.body = oai_error("badArgument", "Set does not exist")
    response = await client.post("/batches", json={"category": "zz.XX", "since": "2026-09-16"})
    assert response.status_code == 422
    assert "Set does not exist" in response.json()["detail"]


async def test_an_arxiv_outage_is_a_bad_gateway(client: AsyncClient, arxiv: FakeArxiv) -> None:
    arxiv.status = 503
    response = await client.post("/batches", json={"category": "cs.IR", "since": "2026-09-16"})
    assert response.status_code == 502
    assert (await client.get("/papers")).json()["total"] == 0


async def test_a_malformed_category_never_reaches_arxiv(
    client: AsyncClient, arxiv: FakeArxiv
) -> None:
    response = await client.post(
        "/batches", json={"category": "cs.IR OR cat:math", "since": "2026-09-16"}
    )
    assert response.status_code == 422
    assert arxiv.requests == []


async def test_a_window_starting_tomorrow_is_rejected(
    client: AsyncClient, arxiv: FakeArxiv
) -> None:
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()
    response = await client.post("/batches", json={"category": "cs.IR", "since": tomorrow})
    assert response.status_code == 422
    assert arxiv.requests == []


async def test_submitting_needs_a_session(anonymous: AsyncClient, arxiv: FakeArxiv) -> None:
    response = await anonymous.post("/batches", json={"category": "cs.IR", "since": "2026-09-16"})
    assert response.status_code == 401
    assert arxiv.requests == []
