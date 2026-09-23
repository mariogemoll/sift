"""What to do after something failed: try again later, or give up for good.

Every stage that talks to the network fails in two ways. Some failures are about
the moment — a reset connection, a 503, a timeout — and deserve another attempt.
Others are about the thing itself — a paper that is gone, a body that is not a
PDF — and would fail identically on every attempt, so they give up at once
instead of spending the attempts a transient failure might need.

This module holds no clock and no randomness: the caller passes the attempt count
and a uniform draw, so every schedule is reproducible in a test.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Retryable:
    """A failure worth another attempt. `retry_after` is the least wait the server asked for."""

    reason: str
    retry_after: float | None = None


@dataclass(frozen=True, slots=True)
class Terminal:
    """A failure every further attempt would repeat."""

    reason: str


type Failure = Retryable | Terminal


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How many attempts an item gets, and how the wait between them grows."""

    max_attempts: int = 5
    base: float = 2.0
    """Ceiling of the first wait, in seconds; each later ceiling doubles."""
    cap: float = 300.0
    """No wait is ever longer than this, in seconds."""

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1, got {self.max_attempts}")
        if self.base <= 0 or self.cap < self.base:
            raise ValueError(f"need 0 < base <= cap, got base={self.base}, cap={self.cap}")


@dataclass(frozen=True, slots=True)
class RetryIn:
    """Try again after this many seconds."""

    delay: float


@dataclass(frozen=True, slots=True)
class GiveUp:
    """Stop trying. `reason` is the last error, so a dead item says why it died."""

    reason: str


type NextStep = RetryIn | GiveUp


def backoff(policy: RetryPolicy, attempt: int, draw: float) -> float:
    """The wait after failed attempt number `attempt`, counting from 1.

    Exponential with full jitter: uniform between zero and a ceiling that doubles
    per attempt up to the cap. Spreading the whole window, rather than adding a
    little noise to a fixed delay, is what keeps many items that failed together
    from all coming back together. `draw` is a uniform sample from [0, 1].
    """
    if attempt < 1:
        raise ValueError(f"attempt counts from 1, got {attempt}")
    if not 0.0 <= draw <= 1.0:
        raise ValueError(f"draw must be in [0, 1], got {draw}")
    # Doubling stops mattering long before the exponent could overflow a float.
    doublings = min(attempt - 1, 64)
    return draw * min(policy.cap, policy.base * 2.0**doublings)


def after_failure(policy: RetryPolicy, attempts: int, failure: Failure, draw: float) -> NextStep:
    """Decide what follows the failure of attempt number `attempts`.

    A server's Retry-After is a floor, never a ceiling: it may lengthen the
    backoff but not shorten it.
    """
    match failure:
        case Terminal(reason):
            return GiveUp(reason)
        case Retryable(reason, retry_after):
            if attempts >= policy.max_attempts:
                return GiveUp(f"{reason} (gave up after {attempts} attempts)")
            return RetryIn(max(backoff(policy, attempts, draw), retry_after or 0.0))
