import pytest

from sift.retry import (
    GiveUp,
    Retryable,
    RetryIn,
    RetryPolicy,
    Terminal,
    after_failure,
    backoff,
)

POLICY = RetryPolicy(max_attempts=4, base=2.0, cap=60.0)


@pytest.mark.parametrize(("attempt", "ceiling"), [(1, 2.0), (2, 4.0), (3, 8.0), (4, 16.0)])
def test_the_backoff_ceiling_doubles_with_each_attempt(attempt: int, ceiling: float) -> None:
    assert backoff(POLICY, attempt, draw=1.0) == ceiling


def test_the_backoff_ceiling_stops_at_the_cap() -> None:
    assert backoff(POLICY, 30, draw=1.0) == 60.0


def test_a_huge_attempt_count_does_not_overflow() -> None:
    assert backoff(POLICY, 10_000, draw=1.0) == 60.0


def test_jitter_spreads_the_delay_over_the_whole_window() -> None:
    assert backoff(POLICY, 3, draw=0.0) == 0.0
    assert backoff(POLICY, 3, draw=0.25) == 2.0


def test_the_draw_must_be_a_fraction() -> None:
    with pytest.raises(ValueError, match="draw"):
        backoff(POLICY, 1, draw=1.5)


def test_attempts_count_from_one() -> None:
    with pytest.raises(ValueError, match="attempt"):
        backoff(POLICY, 0, draw=0.5)


def test_a_retryable_failure_is_retried_after_a_backoff() -> None:
    assert after_failure(POLICY, 1, Retryable("reset"), draw=0.5) == RetryIn(1.0)


def test_a_server_asking_for_longer_than_the_backoff_is_obeyed() -> None:
    assert after_failure(POLICY, 1, Retryable("busy", retry_after=30.0), draw=0.5) == RetryIn(30.0)


def test_a_server_asking_for_less_than_the_backoff_does_not_shorten_it() -> None:
    assert after_failure(POLICY, 3, Retryable("busy", retry_after=1.0), draw=1.0) == RetryIn(8.0)


def test_a_terminal_failure_gives_up_at_once_without_spending_attempts() -> None:
    assert after_failure(POLICY, 1, Terminal("404 Not Found"), draw=0.5) == GiveUp("404 Not Found")


def test_the_last_attempt_gives_up_and_keeps_the_last_error() -> None:
    outcome = after_failure(POLICY, 4, Retryable("503 Service Unavailable"), draw=0.5)
    assert outcome == GiveUp("503 Service Unavailable (gave up after 4 attempts)")


def test_a_policy_needs_at_least_one_attempt() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        RetryPolicy(max_attempts=0)
