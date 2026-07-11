"""Tests for Redis-first hot cache and stale fallback behavior."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from china_quant_platform.infrastructure.cache_backend import MemoryCacheBackend
from china_quant_platform.infrastructure.cached_service import CachedApplicationService, _cache_key


class CountingService:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    def analyze(self, _payload: object) -> dict[str, object]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider disconnected")
        return {
            "ok": True,
            "dataHealth": {"status": "HEALTHY", "block_signal": False, "issues": []},
        }


def test_memory_cache_hits_without_repeating_business_call() -> None:
    async def scenario() -> None:
        raw = CountingService()
        service = CachedApplicationService(raw, MemoryCacheBackend())
        first = await service.analyze({"query": "513300"})
        second = await service.analyze({"query": "513300"})
        assert raw.calls == 1
        assert first["cache"]["status"] == "MISS"
        assert second["cache"]["status"] == "HIT"

    asyncio.run(scenario())


def test_expired_cache_is_returned_as_stale_and_blocks_signal() -> None:
    async def scenario() -> None:
        raw = CountingService()
        backend = MemoryCacheBackend()
        service = CachedApplicationService(raw, backend)
        await service.analyze({"query": "513300"})
        key = _cache_key("analyze", {"query": "513300"})
        record = backend._records[key]
        backend._records[key] = record.__class__(
            value=record.value,
            stored_at=record.stored_at,
            expires_at=datetime.now(tz=UTC) - timedelta(seconds=1),
        )
        raw.fail = True
        result = await service.analyze({"query": "513300"})
        assert result["cache"]["status"] == "STALE"
        assert result["dataHealth"]["status"] == "STALE"
        assert result["dataHealth"]["block_signal"] is True

    asyncio.run(scenario())
