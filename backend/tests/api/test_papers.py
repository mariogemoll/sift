from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sift.storage.models import Paper, Verdict


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
    assert [item["paper"]["title"] for item in body["items"]] == ["Newer", "Older"]
    assert body["items"][0]["paper"]["authors"] == ["B. Author", "C. Author"]


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
    assert [item["paper"]["title"] for item in body["items"]] == ["Paper 4", "Paper 3"]


async def test_days_keeps_to_recently_published_papers(
    client: AsyncClient, session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    session.add_all(
        [
            Paper(
                arxiv_id=f"2609.{age:05d}",
                title=f"{age} days old",
                authors=[],
                categories=[],
                published_at=now - timedelta(days=age, hours=1),
                abstract="",
            )
            for age in (0, 3, 10)
        ]
    )
    await session.commit()

    body = (await client.get("/papers", params={"days": 7})).json()

    assert body["total"] == 2
    assert [item["paper"]["title"] for item in body["items"]] == ["0 days old", "3 days old"]
    assert (await client.get("/papers", params={"days": 0})).status_code == 422


async def test_newest_ignores_verdicts(client: AsyncClient, session: AsyncSession) -> None:
    session.add_all(
        [
            Paper(
                arxiv_id="2609.00001",
                title="Older",
                authors=[],
                categories=[],
                published_at=datetime(2026, 9, 1, tzinfo=UTC),
                abstract="",
            ),
            Paper(
                arxiv_id="2609.00002",
                title="Newer",
                authors=[],
                categories=[],
                published_at=datetime(2026, 9, 2, tzinfo=UTC),
                abstract="",
            ),
        ]
    )
    await session.flush()
    older = await session.scalar(select(Paper.id).where(Paper.title == "Older"))
    assert older is not None
    session.add(
        Verdict(
            paper_id=older,
            profile="test",
            stage="full",
            eligible=True,
            total=0.9,
            merit=0.9,
            fit=0.9,
            blocked_by=[],
            needs_review=False,
            notes=[],
            per_criterion={"robotics": 0.9},
            judgment_key="k",
        )
    )
    await session.commit()

    ranked = (await client.get("/papers")).json()["items"]
    newest = (await client.get("/papers", params={"order": "newest"})).json()["items"]

    assert [item["paper"]["title"] for item in ranked] == ["Older", "Newer"]
    assert ranked[0]["verdict"]["per_criterion"] == {"robotics": 0.9}
    assert ranked[1]["verdict"] is None
    assert [item["paper"]["title"] for item in newest] == ["Newer", "Older"]


async def test_the_wishlist_is_readable(client: AsyncClient) -> None:
    body = (await client.get("/profile")).json()

    assert body["name"] == "test"
    assert [(c["id"], c["kind"]) for c in body["criteria"]] == [
        ("robotics", "want"),
        ("retracted", "dealbreaker"),
    ]
    assert body["screen_threshold"] == 0.5


async def test_the_wishlist_needs_a_session(anonymous: AsyncClient) -> None:
    assert (await anonymous.get("/profile")).status_code == 401
