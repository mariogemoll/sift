from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from arxiv_fake import FakeArxiv
from sift.core.profile import ProfileError
from sift.pipeline import wishlist


async def submit(client: AsyncClient) -> list[dict[str, object]]:
    response = await client.post("/batches")
    assert response.status_code == 202
    body: list[dict[str, object]] = response.json()
    return body


async def test_submitting_queues_a_batch_without_asking_arxiv(
    client: AsyncClient, arxiv: FakeArxiv
) -> None:
    (body,) = await submit(client)

    assert (body["category"], body["state"], body["status"]) == ("cs.RO", "queued", "queued")
    assert (body["announced"], body["items"], body["attempts"]) == (None, 0, 0)
    assert body["progress"] == {}
    assert arxiv.requests == []


async def test_one_batch_per_category_the_wishlist_names(app: FastAPI, client: AsyncClient) -> None:
    app.state.profile = replace(app.state.profile, categories=("cs.AI", "cs.CL", "hep-th"))

    queued = await submit(client)

    assert [batch["category"] for batch in queued] == ["cs.AI", "cs.CL", "hep-th"]
    listed = (await client.get("/batches")).json()
    assert [item["category"] for item in listed] == ["hep-th", "cs.CL", "cs.AI"]
    assert len((await client.get("/batches", params={"limit": 2})).json()) == 2


async def test_one_batch_by_id(client: AsyncClient) -> None:
    (created,) = await submit(client)
    assert (await client.get(f"/batches/{created['id']}")).json() == created


async def test_an_unknown_batch_is_not_found(client: AsyncClient) -> None:
    assert (await client.get("/batches/12345")).status_code == 404


async def test_batches_need_a_session(anonymous: AsyncClient) -> None:
    submitted = await anonymous.post("/batches")
    assert submitted.status_code == 401
    assert (await anonymous.get("/batches")).status_code == 401


WANT = '[[want]]\nid = "x"\nrequirement = "r"\n'


def test_a_wishlist_must_name_a_category_to_harvest(tmp_path: Path) -> None:
    path = tmp_path / "wishlist.toml"
    path.write_text(WANT)
    with pytest.raises(ProfileError, match="no categories"):
        wishlist.load(path)


def test_a_malformed_category_stops_the_wishlist_loading(tmp_path: Path) -> None:
    path = tmp_path / "wishlist.toml"
    path.write_text('categories = ["cs.AI", "cs.IR OR cat:math"]\n' + WANT)
    with pytest.raises(ProfileError, match="cs.IR OR cat:math"):
        wishlist.load(path)


def test_the_shipped_wishlist_loads() -> None:
    shipped = wishlist.load(Path(__file__).resolve().parents[2] / "wishlist.toml")
    assert shipped.categories
    assert shipped.wants and shipped.dealbreakers
