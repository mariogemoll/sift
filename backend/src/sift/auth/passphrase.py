"""The passphrase and the session tokens it signs.

One shared passphrase guards the web interface. The server holds an scrypt hash
of it and never the phrase itself, and the key that signs session cookies is
derived from that hash rather than configured beside it:

    signing key = HMAC(scrypt hash, "sift session v1")

So there is a single secret to hold, and changing the passphrase changes the
hash, which changes the key, which invalidates every session already handed
out. The hash never leaves the server, which is what makes it usable as key
material; the domain string keeps the two uses of it apart.

Everything here is deterministic — the caller supplies the salt and the current
time — so there is no clock and no randomness for a test to stub.
"""

import hashlib
import hmac
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass

SALT_BYTES = 16
"""Salt length for a new hash. Callers generate the salt; this module never does."""

_SCHEME = "scrypt"
_COST = 16384
_BLOCK_SIZE = 8
_PARALLELISM = 1
_KEY_BYTES = 32
_SESSION_INFO = b"sift session v1"


def _encode(raw: bytes) -> str:
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(text: str) -> bytes:
    """Undo `_encode`. Raises ValueError on anything that is not base64url."""
    return urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True, slots=True)
class _Hash:
    """A stored hash, taken apart."""

    cost: int
    block_size: int
    parallelism: int
    salt: bytes
    key: bytes


def _derive(passphrase: str, salt: bytes, cost: int, block_size: int, parallelism: int) -> bytes:
    return hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=salt,
        n=cost,
        r=block_size,
        p=parallelism,
        dklen=_KEY_BYTES,
    )


def hash_passphrase(passphrase: str, salt: bytes) -> str:
    """Hash `passphrase` into the one string the server stores.

    The cost parameters travel with the hash, so raising them later leaves
    phrases hashed at the old cost still verifiable.
    """
    key = _derive(passphrase, salt, _COST, _BLOCK_SIZE, _PARALLELISM)
    fields = (_SCHEME, _COST, _BLOCK_SIZE, _PARALLELISM, _encode(salt), _encode(key))
    return "$".join(str(field) for field in fields)


def _parse(stored: str) -> _Hash | None:
    """Read a stored hash back, or None if it is not one."""
    scheme, _, rest = stored.partition("$")
    if scheme != _SCHEME:
        return None
    fields = rest.split("$")
    if len(fields) != 5:
        return None
    cost, block_size, parallelism, salt, key = fields
    try:
        return _Hash(int(cost), int(block_size), int(parallelism), _decode(salt), _decode(key))
    except ValueError:
        return None


def verify_passphrase(passphrase: str, stored: str) -> bool:
    """Whether `passphrase` is the one `stored` was made from.

    Deliberately slow — scrypt is the cost of a guess.
    """
    parsed = _parse(stored)
    if parsed is None:
        return False
    offered = _derive(passphrase, parsed.salt, parsed.cost, parsed.block_size, parsed.parallelism)
    return hmac.compare_digest(offered, parsed.key)


def session_key(stored: str) -> bytes | None:
    """The cookie signing key a stored hash implies, or None if it is not one."""
    parsed = _parse(stored)
    if parsed is None:
        return None
    return hmac.new(parsed.key, _SESSION_INFO, hashlib.sha256).digest()


def _sign(key: bytes, expires_at: int) -> bytes:
    return hmac.new(key, str(expires_at).encode("ascii"), hashlib.sha256).digest()


def mint_session(key: bytes, expires_at: int) -> str:
    """A cookie value carrying its own expiry, good until `expires_at` (epoch seconds)."""
    return f"{expires_at}.{_encode(_sign(key, expires_at))}"


def session_valid(key: bytes, token: str, now: int) -> bool:
    """Whether `token` carries our signature and has not expired.

    The expiry is inside the signature, so the server keeps no session table:
    a cookie is self-describing and either verifies or does not.
    """
    expiry, _, signature = token.partition(".")
    if not (expiry.isascii() and expiry.isdigit()):
        return False
    expires_at = int(expiry)
    try:
        offered = _decode(signature)
    except ValueError:
        return False
    if not hmac.compare_digest(offered, _sign(key, expires_at)):
        return False
    return now < expires_at
