"""Async rate limiter tests."""

from __future__ import annotations

import asyncio

from china_quant_platform.data import AsyncRateLimiter


def test_async_rate_limiter_waits_after_capacity_is_exhausted() -> None:
    async def run_scenario() -> list[float]:
        now = 0.0
        sleeps: list[float] = []

        def clock() -> float:
            return now

        async def sleep(delay: float) -> None:
            nonlocal now
            sleeps.append(delay)
            now += delay

        limiter = AsyncRateLimiter(max_calls=1, period_seconds=2.5, sleep=sleep, clock=clock)

        await limiter.acquire()
        await limiter.acquire()
        return sleeps

    assert asyncio.run(run_scenario()) == [2.5]
