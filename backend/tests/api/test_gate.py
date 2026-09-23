from httpx import AsyncClient

from sift.api.gate import COOKIE
from sift.core.auth import hash_passphrase, mint_session, session_key


async def test_a_visitor_is_not_signed_in_but_could_be(anonymous: AsyncClient) -> None:
    body = (await anonymous.get("/auth/session")).json()
    assert body == {"authenticated": False, "configured": True}


async def test_the_right_passphrase_sets_a_session_cookie(
    anonymous: AsyncClient, passphrase: str
) -> None:
    response = await anonymous.post("/auth/session", json={"passphrase": passphrase})
    assert response.status_code == 200
    assert response.json() == {"authenticated": True, "configured": True}

    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert (await anonymous.get("/auth/session")).json()["authenticated"] is True


async def test_the_wrong_passphrase_gets_nothing(anonymous: AsyncClient) -> None:
    response = await anonymous.post("/auth/session", json={"passphrase": "not it"})
    assert response.status_code == 401
    assert COOKIE not in anonymous.cookies
    assert (await anonymous.get("/auth/session")).json()["authenticated"] is False


async def test_an_empty_passphrase_is_rejected_before_it_is_checked(
    anonymous: AsyncClient,
) -> None:
    assert (await anonymous.post("/auth/session", json={"passphrase": ""})).status_code == 422


async def test_reading_papers_needs_a_session(anonymous: AsyncClient) -> None:
    assert (await anonymous.get("/papers")).status_code == 401


async def test_reading_papers_works_with_one(client: AsyncClient) -> None:
    assert (await client.get("/papers")).status_code == 200


async def test_signing_out_closes_the_door_again(client: AsyncClient) -> None:
    assert (await client.delete("/auth/session")).status_code == 204
    assert COOKIE not in client.cookies
    assert (await client.get("/papers")).status_code == 401


def _key(stored_hash: str) -> bytes:
    key = session_key(stored_hash)
    assert key is not None
    return key


async def test_a_cookie_signed_with_another_key_is_not_a_session(
    anonymous: AsyncClient,
) -> None:
    elsewhere = _key(hash_passphrase("some other deployment", b"a fixed 16 bytes"))
    anonymous.cookies.set(COOKIE, mint_session(elsewhere, expires_at=9_999_999_999))
    assert (await anonymous.get("/papers")).status_code == 401


async def test_a_cookie_that_is_not_a_token_is_not_a_session(anonymous: AsyncClient) -> None:
    anonymous.cookies.set(COOKIE, "let me in")
    assert (await anonymous.get("/papers")).status_code == 401


async def test_an_expired_cookie_is_not_a_session(
    anonymous: AsyncClient, passphrase_hash: str
) -> None:
    """Authentic signature, spent lifetime: the expiry is inside what we signed."""
    anonymous.cookies.set(COOKIE, mint_session(_key(passphrase_hash), expires_at=1))
    assert (await anonymous.get("/papers")).status_code == 401


async def test_health_stays_open_because_the_load_balancer_polls_it(
    anonymous: AsyncClient,
) -> None:
    assert (await anonymous.get("/health")).status_code == 200


async def test_a_deployment_with_no_passphrase_admits_nobody(
    closed: AsyncClient, passphrase: str
) -> None:
    assert (await closed.get("/auth/session")).json() == {
        "authenticated": False,
        "configured": False,
    }
    assert (await closed.post("/auth/session", json={"passphrase": passphrase})).status_code == 503
    assert (await closed.get("/papers")).status_code == 401
