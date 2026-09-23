"""The passphrase gate: one shared secret, one signed cookie, no accounts.

Signing in costs a round trip; after that the browser carries a cookie and the
passphrase is not on the wire again. That is the difference from HTTP Basic,
along with a page we control and a logout that means something.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, Response, status

from sift.core.auth import mint_session, session_key, session_valid
from sift.settings import Settings

COOKIE = "sift_session"


@dataclass(frozen=True, slots=True)
class Gate:
    """What the app needs to hand out cookies and check them.

    `key` is None when no usable passphrase hash is configured, and that is what
    closes the door: nothing to sign with, nothing to check against, so every
    request stays out until the secret is in place.
    """

    stored_hash: str
    key: bytes | None
    lifetime: timedelta
    secure: bool


def build(settings: Settings) -> Gate:
    return Gate(
        stored_hash=settings.passphrase_hash,
        key=session_key(settings.passphrase_hash),
        lifetime=timedelta(hours=settings.session_hours),
        secure=settings.cookie_secure,
    )


def configured(gate: Gate) -> bool:
    """Whether a passphrase hash is present and readable."""
    return gate.key is not None


def admits(gate: Gate, request: Request, now: datetime) -> bool:
    """Whether this request carries a cookie we signed and that has not expired."""
    token = request.cookies.get(COOKIE)
    if gate.key is None or token is None:
        return False
    return session_valid(gate.key, token, int(now.timestamp()))


def grant(gate: Gate, response: Response, now: datetime) -> None:
    """Set a fresh session cookie on `response`."""
    if gate.key is None:
        raise RuntimeError("no passphrase configured")
    expires_at = int((now + gate.lifetime).timestamp())
    response.set_cookie(
        COOKIE,
        mint_session(gate.key, expires_at),
        max_age=int(gate.lifetime.total_seconds()),
        httponly=True,
        secure=gate.secure,
        samesite="strict",
        path="/",
    )


def revoke(gate: Gate, response: Response) -> None:
    """Clear the session cookie. The token stays valid; the browser no longer has it."""
    response.delete_cookie(COOKIE, httponly=True, secure=gate.secure, samesite="strict", path="/")


def of(request: Request) -> Gate:
    gate: Gate = request.app.state.gate
    return gate


def guard(request: Request) -> None:
    """Dependency for routers that require a session."""
    if not admits(of(request), request, datetime.now(UTC)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not signed in")
