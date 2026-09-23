"""What happens to a batch when a step fails. Pure: the caller supplies the count."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

MAX_ATTEMPTS = 5
FIRST_DELAY = timedelta(seconds=10)
LONGEST_DELAY = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class AfterFailure:
    """The state a failed batch moves to, and how long before it may be tried again."""

    state: Literal["harvesting", "failed"]
    delay: timedelta


def after_failure(attempts: int, *, retryable: bool) -> AfterFailure:
    """`attempts` counts the one that just failed.

    A failure that asking again cannot fix ends the batch at once; any other
    doubles the wait each time, up to a ceiling, until the attempts run out.
    """
    if not retryable or attempts >= MAX_ATTEMPTS:
        return AfterFailure(state="failed", delay=timedelta(0))
    return AfterFailure(
        state="harvesting", delay=min(FIRST_DELAY * 2 ** (attempts - 1), LONGEST_DELAY)
    )
