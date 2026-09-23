"""Sorting what went wrong on the wire into retryable and terminal.

Server trouble and throttling retry: 5xx, 408, 425, 429, and anything that broke
the connection. A paper that is not there, and any other client error, is
terminal — asking again gets the same answer.
"""

from datetime import datetime
from email.utils import parsedate_to_datetime
from http import HTTPStatus

import httpx

from sift.retry import Failure, Retryable, Terminal

_RETRYABLE_CLIENT_ERRORS = frozenset({408, 425, 429})
# Transport errors caused by the network or the far end. The rest of httpx's
# errors — an unsupported scheme, a malformed request, a redirect loop, a body
# that cannot be decoded — are ours or the server's to fix, not the moment's.
_TRANSIENT_ERRORS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
    httpx.ProxyError,
)


class FetchFailed(RuntimeError):
    """Fetching a document failed; `failure` says whether it is worth another attempt."""

    def __init__(self, failure: Failure) -> None:
        super().__init__(failure.reason)
        self.failure = failure


def retry_after(value: str | None, now: datetime) -> float | None:
    """Seconds to wait from a Retry-After header — delta-seconds or an HTTP-date.

    Anything unreadable is ignored rather than trusted, and a date already past
    means now.
    """
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        return None
    return max(0.0, (when - now).total_seconds())


def _status_reason(status: int) -> str:
    try:
        return f"HTTP {status} {HTTPStatus(status).phrase}"
    except ValueError:
        return f"HTTP {status}"


def from_status(status: int, headers: httpx.Headers, now: datetime) -> Failure:
    """The failure an unsuccessful response stands for."""
    reason = _status_reason(status)
    if status >= 500 or status in _RETRYABLE_CLIENT_ERRORS:
        return Retryable(reason, retry_after=retry_after(headers.get("retry-after"), now))
    return Terminal(reason)


def from_error(error: httpx.HTTPError) -> Failure:
    """The failure a request that raised stands for."""
    reason = str(error) or type(error).__name__
    if isinstance(error, _TRANSIENT_ERRORS):
        return Retryable(reason)
    return Terminal(reason)
