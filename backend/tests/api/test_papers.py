from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from sift.storage.models import Paper


async def test_papers_is_empty_before_anything_is_ingested(
    client: AsyncClient,
) -> None:
    response = await client.get("/papers")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_papers_echoes_the_requested_window(client: AsyncClient) -> None:
    body = (await client.get("/papers", params={"limit": 10, "offset": 20})).json()
    assert (body["limit"], body["offset"]) == (10, 20)


async def test_papers_rejects_a_window_outside_the_allowed_range(
    client: AsyncClient,
) -> None:
    assert (await client.get("/papers", params={"limit": 0})).status_code == 422
    assert (await client.get("/papers", params={"limit": 500})).status_code == 422
    assert (await client.get("/papers", params={"offset": -1})).status_code == 422


async def test_papers_returns_stored_rows_newest_first(
    client: AsyncClient, session: AsyncSession
) -> None:
    session.add_all(
        [
            Paper(
                arxiv_id="2401.00001",
                title="Older",
                authors=["A. Author"],
                categories=["cs.IR"],
                published_at=datetime(2024, 1, 1, tzinfo=UTC),
                abstract="first",
            ),
            Paper(
                arxiv_id="2402.00002",
                title="Newer",
                authors=["B. Author", "C. Author"],
                categories=["cs.IR", "cs.CL"],
                published_at=datetime(2024, 2, 1, tzinfo=UTC),
                abstract="second",
            ),
        ]
    )
    await session.commit()

    body = (await client.get("/papers")).json()
    assert body["total"] == 2
    assert [item["title"] for item in body["items"]] == ["Newer", "Older"]
    assert body["items"][0]["authors"] == ["B. Author", "C. Author"]


async def test_the_window_slices_a_longer_list(client: AsyncClient, session: AsyncSession) -> None:
    session.add_all(
        [
            Paper(
                arxiv_id=f"2401.{index:05d}",
                title=f"Paper {index}",
                authors=[],
                categories=[],
                published_at=datetime(2024, 1, index, tzinfo=UTC),
                abstract="",
            )
            for index in range(1, 6)
        ]
    )
    await session.commit()

    body = (await client.get("/papers", params={"limit": 2, "offset": 1})).json()
    assert body["total"] == 5
    assert [item["title"] for item in body["items"]] == ["Paper 4", "Paper 3"]
