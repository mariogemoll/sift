from sift.core.auth import (
    hash_passphrase,
    mint_session,
    session_key,
    session_valid,
    verify_passphrase,
)

SALT = b"sixteen bytes!!!"
OTHER_SALT = b"another 16 bytes"


def test_a_hashed_passphrase_verifies_against_itself() -> None:
    stored = hash_passphrase("open sesame", SALT)
    assert verify_passphrase("open sesame", stored)


def test_a_different_passphrase_does_not() -> None:
    stored = hash_passphrase("open sesame", SALT)
    assert not verify_passphrase("open sesam", stored)
    assert not verify_passphrase("", stored)


def test_the_same_passphrase_hashes_differently_under_a_different_salt() -> None:
    assert hash_passphrase("open sesame", SALT) != hash_passphrase("open sesame", OTHER_SALT)


def test_the_cost_travels_with_the_hash() -> None:
    """So that raising the cost later does not strand phrases hashed at the old one."""
    scheme, cost, block_size, parallelism, _, _ = hash_passphrase("x", SALT).split("$")
    assert scheme == "scrypt"
    assert (int(cost), int(block_size), int(parallelism)) == (16384, 8, 1)


def test_nothing_verifies_against_a_value_that_is_not_a_hash() -> None:
    for stored in ["", "hunter2", "scrypt$", "scrypt$a$b$c$d$e", "bcrypt$1$2$3$4$5"]:
        assert not verify_passphrase("hunter2", stored)
        assert session_key(stored) is None


def test_the_signing_key_follows_the_passphrase() -> None:
    """Rotating the passphrase must invalidate sessions, and this is why it does."""
    assert session_key(hash_passphrase("before", SALT)) != session_key(
        hash_passphrase("after", SALT)
    )


def test_the_signing_key_is_stable_for_one_stored_hash() -> None:
    stored = hash_passphrase("open sesame", SALT)
    assert session_key(stored) == session_key(stored)


def _key(passphrase: str = "open sesame") -> bytes:
    key = session_key(hash_passphrase(passphrase, SALT))
    assert key is not None
    return key


def test_a_minted_token_is_valid_until_it_expires() -> None:
    key = _key()
    token = mint_session(key, expires_at=1_000)
    assert session_valid(key, token, now=999)
    assert not session_valid(key, token, now=1_000)
    assert not session_valid(key, token, now=1_001)


def test_a_token_minted_under_another_key_is_refused() -> None:
    token = mint_session(_key("before"), expires_at=1_000)
    assert not session_valid(_key("after"), token, now=1)


def test_a_tampered_signature_is_refused() -> None:
    key = _key()
    expiry, _, signature = mint_session(key, expires_at=1_000).partition(".")
    assert not session_valid(key, f"{expiry}.{signature[:-2]}AA", now=1)


def test_pushing_the_expiry_out_invalidates_the_signature() -> None:
    key = _key()
    _, _, signature = mint_session(key, expires_at=1_000).partition(".")
    assert not session_valid(key, f"9999999999.{signature}", now=1)


def test_a_token_that_is_not_one_is_refused() -> None:
    key = _key()
    for token in ["", ".", "1000", "1000.", "abc.def", "1000.!!!", " 1000.AAAA", "٩٩.AAAA"]:
        assert not session_valid(key, token, now=1)
