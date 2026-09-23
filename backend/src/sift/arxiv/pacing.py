"""Taking turns at a host that allows one request at a time, at a set interval.

arXiv asks for no more than one request every three seconds, on a single
connection. That is a rate, not a concurrency bound: a semaphore of one would
let requests run back to back. A `Pacer` gives out turns one at a time and
keeps each turn from starting until the interval has passed since the previous
one ended.

Counting from the end rather than the start is the conservative reading: a slow
download followed at once by the next would put two requests on the wire with
no gap between them.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager


class Pacer:
    """One turn at a time, at least `interval` seconds apart, for one host."""

    def __init__(
        self,
        interval: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if interval < 0:
            raise ValueError(f"interval cannot be negative, got {interval}")
        self._interval = interval
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._ready_at = float("-inf")

    @asynccontextmanager
    async def turn(self) -> AsyncIterator[None]:
        """Wait for the host to be free and the interval to pass, then hold it until exit."""
        async with self._lock:
            wait = self._ready_at - self._clock()
            if wait > 0:
                await self._sleep(wait)
            try:
                yield
            finally:
                self._push_back(self._interval)

    def hold(self, seconds: float) -> None:
        """Keep every later turn from starting for `seconds` from now.

        For a host that said Retry-After: throttling is about the host, not about
        the one request that happened to be refused.
        """
        self._push_back(seconds)

    def _push_back(self, seconds: float) -> None:
        self._ready_at = max(self._ready_at, self._clock() + seconds)
