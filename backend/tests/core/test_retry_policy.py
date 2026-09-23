from datetime import timedelta

import pytest

from sift.core.batches import LONGEST_DELAY, MAX_ATTEMPTS, after_failure


def test_the_wait_doubles_with_each_attempt() -> None:
    delays = [after_failure(attempt, retryable=True).delay for attempt in range(1, 5)]
    assert delays == [timedelta(seconds=seconds) for seconds in (10, 20, 40, 80)]


def test_a_retryable_failure_keeps_the_batch_going() -> None:
    assert after_failure(1, retryable=True).state == "harvesting"


def test_the_last_attempt_fails_the_batch() -> None:
    outcome = after_failure(MAX_ATTEMPTS, retryable=True)
    assert (outcome.state, outcome.delay) == ("failed", timedelta(0))


@pytest.mark.parametrize("attempt", [1, 3])
def test_a_terminal_failure_ends_it_at_once(attempt: int) -> None:
    assert after_failure(attempt, retryable=False).state == "failed"


def test_the_wait_never_exceeds_the_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sift.core.batches.MAX_ATTEMPTS", 100)
    assert after_failure(30, retryable=True).delay == LONGEST_DELAY
