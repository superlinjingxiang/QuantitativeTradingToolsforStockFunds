"""Cache-aware adapter around the existing Python application service."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from china_quant_platform.infrastructure.cache_backend import CacheBackend

CACHE_SCHEMA_VERSION = "v5"


class CachedApplicationService:
    """Preserve one business service while adding hot-cache behavior."""

    TTL_SECONDS = {
        "health": 5,
        "search": 600,
        "market_overview": 10,
        "analyze": 15,
        "recommendations": 60,
    }

    def __init__(self, service: Any, backend: CacheBackend) -> None:
        self._service = service
        self._backend = backend
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    @property
    def backend(self) -> CacheBackend:
        return self._backend

    async def health(self) -> dict[str, Any]:
        return await self._cached("health", {}, self._service.health)

    async def search(self, query: str) -> dict[str, Any]:
        return await self._cached("search", {"q": query}, lambda: self._service.search(query))

    async def market_overview(self) -> dict[str, Any]:
        return await self._cached("market_overview", {}, self._service.market_overview)

    async def analyze(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return await self._cached("analyze", dict(payload), lambda: self._service.analyze(payload))

    async def recommendations(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return await self._cached(
            "recommendations",
            dict(payload),
            lambda: self._service.recommendations(payload),
        )

    async def _cached(
        self,
        namespace: str,
        payload: Mapping[str, Any],
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        key = _cache_key(namespace, payload)
        cached = await self._backend.get(key)
        if cached is not None:
            return _with_cache_metadata(cached.value, status="HIT", cached_at=cached.stored_at)

        lock = await self._lock_for(key)
        async with lock:
            cached = await self._backend.get(key)
            if cached is not None:
                return _with_cache_metadata(cached.value, status="HIT", cached_at=cached.stored_at)
            try:
                value = await asyncio.to_thread(operation)
            except Exception as error:
                stale = await self._backend.get_stale(key)
                if stale is None:
                    raise
                return _stale_response(stale.value, stale.stored_at, str(error))
            await self._backend.set(key, copy.deepcopy(value), self.TTL_SECONDS[namespace])
            return _with_cache_metadata(value, status="MISS", cached_at=datetime.now(tz=UTC))

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._locks_guard:
            return self._locks.setdefault(key, asyncio.Lock())


def _cache_key(namespace: str, payload: Mapping[str, Any]) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
    return f"{namespace}:{CACHE_SCHEMA_VERSION}:{digest}"


def _with_cache_metadata(
    value: Mapping[str, Any],
    *,
    status: str,
    cached_at: datetime,
) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    result["cache"] = {
        "status": status,
        "cachedAt": cached_at.isoformat(),
        "source": "redis_or_memory",
    }
    return result


def _stale_response(value: Mapping[str, Any], cached_at: datetime, error: str) -> dict[str, Any]:
    result = _with_cache_metadata(value, status="STALE", cached_at=cached_at)
    result["cache"]["error"] = error[:300]
    health = result.get("dataHealth")
    if isinstance(health, dict):
        health["status"] = "STALE"
        health["block_signal"] = True
        issues = list(health.get("issues") or [])
        issues.append(f"数据源刷新失败，已保留缓存：{error[:180]}")
        health["issues"] = issues[-5:]
    return result
