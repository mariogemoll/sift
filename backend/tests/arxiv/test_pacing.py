import asyncio

import pytest

from clock_fake import FakeClock
from sift.arxiv.pacing import Pacer


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(now=1000.0)


def _pacer(clock: FakeClock, interval: float = 3.0) -> Pacer:
    return Pacer(interval, clock=clock, sleep=clock.sleep)


async def test_the_first_turn_does_not_wait(clock: FakeClock) -> None:
    async with _pacer(clock).turn():
        pass
    assert clock.slept == []


async def test_the_next_turn_waits_out_the_interval(clock: FakeClock) -> None:
    pacer = _pacer(clock)
    async with pacer.turn():
        pass
    clock.now += 1.0
    async with pacer.turn():
        pass
    assert clock.slept == [2.0]


async def test_the_interval_counts_from_when_the_previous_request_finished(
    clock: FakeClock,
) -> None:
    pacer = _pacer(clock)
    async with pacer.turn():
        clock.now += 10.0  # a slow download
    async with pacer.turn():
        pass
    assert clock.slept == [3.0]


async def test_concurrent_callers_take_turns_one_at_a_time(clock: FakeClock) -> None:
    pacer = _pacer(clock)
    spans: list[tuple[float, float]] = []

    async def request() -> None:
        async with pacer.turn():
            start = clock.now
            await clock.sleep(0.5)
            spans.append((start, clock.now))

    await asyncio.gather(*(request() for _ in range(4)))

    assert len(spans) == 4
    for (_, previous_end), (start, _) in zip(spans, spans[1:], strict=False):
        assert start - previous_end >= 3.0


async def test_hold_pushes_back_every_later_turn(clock: FakeClock) -> None:
    pacer = _pacer(clock)
    async with pacer.turn():
        pacer.hold(60.0)
    async with pacer.turn():
        pass
    assert clock.slept == [60.0]


async def test_a_hold_shorter_than_the_interval_does_not_shorten_it(clock: FakeClock) -> None:
    pacer = _pacer(clock)
    async with pacer.turn():
        pacer.hold(1.0)
    async with pacer.turn():
        pass
    assert clock.slept == [3.0]


async def test_a_turn_that_raises_still_spaces_the_next(clock: FakeClock) -> None:
    pacer = _pacer(clock)
    with pytest.raises(RuntimeError):
        async with pacer.turn():
            raise RuntimeError("the request failed")
    async with pacer.turn():
        pass
    assert clock.slept == [3.0]


async def test_a_cancelled_waiter_gives_up_its_place(clock: FakeClock) -> None:
    pacer = _pacer(clock)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with pacer.turn():
            entered.set()
            await release.wait()

    async def waiter() -> None:
        async with pacer.turn():
            pass

    holding = asyncio.create_task(holder())
    await entered.wait()
    waiting = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    waiting.cancel()
    release.set()
    await holding
    with pytest.raises(asyncio.CancelledError):
        await waiting

    async with pacer.turn():
        pass


def test_the_interval_cannot_be_negative() -> None:
    with pytest.raises(ValueError, match="interval"):
        Pacer(-1.0)
