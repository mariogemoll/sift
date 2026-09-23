from datetime import UTC, datetime

import httpx
import pytest

from sift.arxiv.failures import from_error, from_status, retry_after
from sift.retry import Retryable, Terminal

NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)


def _headers(**values: str) -> httpx.Headers:
    return httpx.Headers({name.replace("_", "-"): value for name, value in values.items()})


@pytest.mark.parametrize("status", [404, 410])
def test_a_paper_that_is_not_there_is_terminal(status: int) -> None:
    assert isinstance(from_status(status, _headers(), NOW), Terminal)


@pytest.mark.parametrize("status", [400, 401, 403, 405, 415])
def test_other_client_errors_are_terminal(status: int) -> None:
    assert isinstance(from_status(status, _headers(), NOW), Terminal)


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504, 599])
def test_server_trouble_and_throttling_are_retryable(status: int) -> None:
    assert isinstance(from_status(status, _headers(), NOW), Retryable)


def test_the_reason_names_the_status() -> None:
    assert from_status(503, _headers(), NOW).reason == "HTTP 503 Service Unavailable"


def test_a_503_with_retry_after_carries_the_wait() -> None:
    assert from_status(503, _headers(retry_after="120"), NOW) == Retryable(
        "HTTP 503 Service Unavailable", retry_after=120.0
    )


def test_retry_after_in_seconds() -> None:
    assert retry_after("45", NOW) == 45.0


def test_retry_after_as_an_http_date() -> None:
    assert retry_after("Wed, 23 Sep 2026 12:01:30 GMT", NOW) == 90.0


def test_retry_after_in_the_past_means_now() -> None:
    assert retry_after("Wed, 23 Sep 2026 11:00:00 GMT", NOW) == 0.0


@pytest.mark.parametrize("value", [None, "", "soon", "-5", "1.5"])
def test_an_unusable_retry_after_is_ignored(value: str | None) -> None:
    assert retry_after(value, NOW) is None


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("refused"),
        httpx.ReadError("connection reset by peer"),
        httpx.WriteError("broken pipe"),
        httpx.ConnectTimeout("slow"),
        httpx.ReadTimeout("slow"),
        httpx.PoolTimeout("busy"),
        httpx.RemoteProtocolError("peer closed connection without sending complete message body"),
        httpx.ProxyError("proxy down"),
    ],
)
def test_transport_trouble_is_retryable(error: httpx.HTTPError) -> None:
    failure = from_error(error)
    assert isinstance(failure, Retryable)
    assert str(error) in failure.reason


@pytest.mark.parametrize(
    "error",
    [
        httpx.UnsupportedProtocol("ftp"),
        httpx.LocalProtocolError("bad header"),
        httpx.TooManyRedirects("loop"),
        httpx.DecodingError("bad gzip"),
    ],
)
def test_mistakes_that_repeat_on_every_attempt_are_terminal(error: httpx.HTTPError) -> None:
    assert isinstance(from_error(error), Terminal)
