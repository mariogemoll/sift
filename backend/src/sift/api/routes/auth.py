"""Signing in and out.

These handlers are sync `def` on purpose: verifying a passphrase runs scrypt,
which is deliberately slow and CPU-bound, and FastAPI runs a sync handler in a
worker thread rather than on the event loop.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status

from sift.api.schemas import SessionStatus, SignIn
from sift.auth import gate
from sift.auth.passphrase import verify_passphrase

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/session")
def read_session(request: Request) -> SessionStatus:
    """Whether the cookie in hand is good. The login page asks this on load."""
    current = gate.of(request)
    return SessionStatus(
        authenticated=gate.admits(current, request, datetime.now(UTC)),
        configured=gate.configured(current),
    )


@router.post("/session")
def create_session(request: Request, response: Response, credentials: SignIn) -> SessionStatus:
    current = gate.of(request)
    if not gate.configured(current):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="no passphrase is configured for this deployment",
        )
    if not verify_passphrase(credentials.passphrase, current.stored_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="that is not the passphrase"
        )
    gate.grant(current, response, datetime.now(UTC))
    return SessionStatus(authenticated=True, configured=True)


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(request: Request, response: Response) -> None:
    gate.revoke(gate.of(request), response)
