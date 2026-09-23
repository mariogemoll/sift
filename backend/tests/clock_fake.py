"""A monotonic clock for code that paces itself, so tests never really wait."""

import asyncio
from dataclasses import dataclass, field


@dataclass
class FakeClock:
    """Reads like `time.monotonic` and moves only when someone sleeps on it."""

    now: float = 0.0
    slept: list[float] = field(default_factory=list)

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds
        await asyncio.sleep(0)
