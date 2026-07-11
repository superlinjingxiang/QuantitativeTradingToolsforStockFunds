"""Hot-cache backends used by the local FastAPI service.

Redis is deliberately an optimization here. Historical Parquet remains the
durable market-data cache, while this module caches short-lived API results and
keeps the last successful response available during provider outages.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class CacheRecord:
    value: dict[str, Any]
    stored_at: datetime
    expires_at: datetime

    @property
    def is_fresh(self) -> bool:
        return datetime.now(tz=UTC) < self.expires_at


class CacheBackend(Protocol):
    async def get(self, key: str) -> CacheRecord | None: ...

    async def get_stale(self, key: str) -> CacheRecord | None: ...

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None: ...

    async def close(self) -> None: ...


class MemoryCacheBackend:
    """Process-local fallback when Redis is not running."""

    def __init__(self) -> None:
        self._records: dict[str, CacheRecord] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> CacheRecord | None:
        record = await self.get_stale(key)
        return record if record is not None and record.is_fresh else None

    async def get_stale(self, key: str) -> CacheRecord | None:
        async with self._lock:
            return self._records.get(key)

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        now = datetime.now(tz=UTC)
        async with self._lock:
            self._records[key] = CacheRecord(
                value=value,
                stored_at=now,
                expires_at=now + timedelta(seconds=max(ttl_seconds, 1)),
            )

    async def close(self) -> None:
        return None


class RedisCacheBackend:
    """Redis-backed cache with a longer physical TTL for stale fallback."""

    def __init__(
        self,
        url: str,
        *,
        namespace: str = "china_quant_platform",
        stale_retention_factor: int = 10,
    ) -> None:
        self.url = url
        self.namespace = namespace
        self.stale_retention_factor = max(stale_retention_factor, 2)
        self._client: Any | None = None

    async def connect(self) -> None:
        try:
            from redis.asyncio import Redis
        except ImportError as exc:  # pragma: no cover - dependency is installed in production.
            raise RuntimeError("Redis 客户端依赖未安装") from exc
        self._client = Redis.from_url(self.url, decode_responses=True)
        await self._client.ping()

    def _key(self, key: str) -> str:
        return f"{self.namespace}:{key}"

    async def get(self, key: str) -> CacheRecord | None:
        record = await self.get_stale(key)
        return record if record is not None and record.is_fresh else None

    async def get_stale(self, key: str) -> CacheRecord | None:
        if self._client is None:
            return None
        raw = await self._client.get(self._key(key))
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            return CacheRecord(
                value=dict(payload["value"]),
                stored_at=datetime.fromisoformat(payload["stored_at"]),
                expires_at=datetime.fromisoformat(payload["expires_at"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            await self._client.delete(self._key(key))
            return None

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        if self._client is None:
            return
        now = datetime.now(tz=UTC)
        ttl = max(ttl_seconds, 1)
        payload = {
            "value": value,
            "stored_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=ttl)).isoformat(),
        }
        await self._client.set(
            self._key(key),
            json.dumps(payload, ensure_ascii=False),
            ex=max(ttl * self.stale_retention_factor, 60),
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


async def build_cache_backend(env: dict[str, str] | None = None) -> CacheBackend:
    """Prefer Redis, but keep source/Electron startup independent of Redis."""

    values = dict(env or os.environ)
    redis_url = values.get("CQP_REDIS_URL", "").strip()
    required = values.get("CQP_REDIS_REQUIRED", "0").strip().lower() in {"1", "true", "yes"}
    if redis_url:
        backend = RedisCacheBackend(
            redis_url,
            namespace=values.get("CQP_CACHE_NAMESPACE", "china_quant_platform"),
        )
        try:
            await backend.connect()
            return backend
        except Exception:
            await backend.close()
            if required:
                raise
    return MemoryCacheBackend()
