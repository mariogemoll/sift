from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from arxiv_fake import FakeArxiv


async def test_submitting_queues_a_batch_without_asking_arxiv(
    client: AsyncClient, arxiv: FakeArxiv
) -> None:
    response = await client.post("/batches", json={"category": "cs.IR", "since": "2026-09-16"})

    assert response.status_code == 202
    body = response.json()
    assert (body["category"], body["since"], body["state"]) == ("cs.IR", "2026-09-16", "queued")
    assert body["until"] == datetime.now(UTC).date().isoformat()
    assert (body["pages"], body["items"], body["attempts"]) == (0, 0, 0)
    assert "matched" not in body
    assert arxiv.requests == []


async def test_batches_list_newest_first(client: AsyncClient) -> None:
    for category in ("cs.IR", "hep-th", "math"):
        await client.post("/batches", json={"category": category, "since": "2026-09-16"})
    listed = (await client.get("/batches")).json()
    assert [item["category"] for item in listed] == ["math", "hep-th", "cs.IR"]
    assert len((await client.get("/batches", params={"limit": 2})).json()) == 2


async def test_one_batch_by_id(client: AsyncClient) -> None:
    created = (
        await client.post("/batches", json={"category": "cs.IR", "since": "2026-09-16"})
    ).json()
    assert (await client.get(f"/batches/{created['id']}")).json() == created


async def test_an_unknown_batch_is_not_found(client: AsyncClient) -> None:
    assert (await client.get("/batches/12345")).status_code == 404


async def test_a_malformed_category_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/batches", json={"category": "cs.IR OR cat:math", "since": "2026-09-16"}
    )
    assert response.status_code == 422


async def test_a_window_starting_tomorrow_is_rejected(client: AsyncClient) -> None:
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()
    response = await client.post("/batches", json={"category": "cs.IR", "since": tomorrow})
    assert response.status_code == 422


async def test_batches_need_a_session(anonymous: AsyncClient) -> None:
    submitted = await anonymous.post("/batches", json={"category": "cs.IR", "since": "2026-09-16"})
    assert submitted.status_code == 401
    assert (await anonymous.get("/batches")).status_code == 401
