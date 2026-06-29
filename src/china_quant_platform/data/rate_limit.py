"""Small async rate limiter used by provider adapters and tests."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from time import monotonic


class AsyncRateLimiter:
    """Sliding-window limiter with deterministic injection points for tests."""

    def __init__(
        self,
        *,
        max_calls: int,
        period_seconds: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_calls < 1:
            raise ValueError("max_calls must be positive")
        if period_seconds <= 0:
            raise ValueError("period_seconds must be positive")
        self._max_calls = max_calls
        self._period_seconds = period_seconds
        self._sleep = sleep
        self._clock = clock
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = self._clock()
                while self._calls and now - self._calls[0] >= self._period_seconds:
                    self._calls.popleft()
                if len(self._calls) < self._max_calls:
                    self._calls.append(now)
                    return
                wait_seconds = self._period_seconds - (now - self._calls[0])

            await self._sleep(max(wait_seconds, 0))
