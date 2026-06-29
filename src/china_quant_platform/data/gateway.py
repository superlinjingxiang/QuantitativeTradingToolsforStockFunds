"""Provider-independent market data gateway."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field

from china_quant_platform.data.cache import HistoricalBarCache
from china_quant_platform.data.provider import BarsRequest, MarketDataProvider
from china_quant_platform.domain import (
    Bar,
    DataHealth,
    DataHealthStatus,
    DataUnavailable,
    Quote,
)
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import SecurityId


class RealtimeConnectionStatus(StrEnum):
    IDLE = "IDLE"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    STALE = "STALE"
    RECONNECTING = "RECONNECTING"
    DISCONNECTED = "DISCONNECTED"
    CANCELLED = "CANCELLED"


class RealtimeSubscriptionState(DomainModel):
    security_ids: tuple[SecurityId, ...]
    status: RealtimeConnectionStatus
    latest_quote: Quote | None = None
    last_event_at: AwareDatetime | None = None
    reconnect_attempts: int = Field(default=0, ge=0)
    backoff_seconds: float = Field(default=0, ge=0)
    last_error: str | None = None

    @classmethod
    def idle(cls, security_ids: Sequence[str]) -> Self:
        return cls(
            security_ids=tuple(security_ids),
            status=RealtimeConnectionStatus.IDLE,
        )

    def with_status(
        self,
        status: RealtimeConnectionStatus,
        *,
        event_at: datetime | None = None,
        reconnect_attempts: int | None = None,
        backoff_seconds: float | None = None,
        last_error: str | None = None,
    ) -> Self:
        return self.model_copy(
            update={
                "status": status,
                "last_event_at": event_at if event_at is not None else self.last_event_at,
                "reconnect_attempts": (
                    reconnect_attempts
                    if reconnect_attempts is not None
                    else self.reconnect_attempts
                ),
                "backoff_seconds": (
                    backoff_seconds if backoff_seconds is not None else self.backoff_seconds
                ),
                "last_error": last_error,
            }
        )

    def with_quote(self, quote: Quote) -> Self:
        return self.model_copy(
            update={
                "status": RealtimeConnectionStatus.CONNECTED,
                "latest_quote": quote,
                "last_event_at": quote.received_at,
                "reconnect_attempts": 0,
                "backoff_seconds": 0,
                "last_error": None,
            }
        )

    def as_data_health(self, now: datetime, stale_after: timedelta) -> DataHealth:
        if self.latest_quote is None:
            return DataHealth(
                status=DataHealthStatus.DEGRADED,
                block_signal=True,
                as_of=now,
                issues=("No realtime quote has been received.",),
            )

        age = now - self.latest_quote.source_time
        if self.status in {
            RealtimeConnectionStatus.RECONNECTING,
            RealtimeConnectionStatus.DISCONNECTED,
            RealtimeConnectionStatus.CANCELLED,
        }:
            return DataHealth(
                status=DataHealthStatus.STALE,
                block_signal=True,
                as_of=now,
                issues=(f"Realtime subscription is {self.status.value}.",),
            )

        if age > stale_after or self.status is RealtimeConnectionStatus.STALE:
            return DataHealth(
                status=DataHealthStatus.STALE,
                block_signal=True,
                as_of=now,
                issues=(f"Realtime quote age {age.total_seconds():.0f}s exceeds threshold.",),
            )

        return DataHealth(
            status=DataHealthStatus.HEALTHY,
            block_signal=False,
            as_of=now,
            issues=(),
        )


class MarketDataGateway:
    """Coordinates provider access, historical cache reads, and realtime state."""

    def __init__(
        self,
        provider: MarketDataProvider,
        bar_cache: HistoricalBarCache,
        *,
        quote_stale_after: timedelta = timedelta(seconds=10),
        reconnect_base_delay: timedelta = timedelta(seconds=1),
        reconnect_max_delay: timedelta = timedelta(seconds=30),
    ) -> None:
        self._provider = provider
        self._bar_cache = bar_cache
        self._quote_stale_after = quote_stale_after
        self._reconnect_base_delay = reconnect_base_delay
        self._reconnect_max_delay = reconnect_max_delay
        self._realtime_states: dict[tuple[str, ...], RealtimeSubscriptionState] = {}

    @property
    def bar_cache(self) -> HistoricalBarCache:
        return self._bar_cache

    async def get_bars(self, request: BarsRequest) -> list[Bar]:
        missing_ranges = self._bar_cache.missing_ranges(request)
        for missing_range in missing_ranges:
            fetched_bars = await self._provider.get_bars(missing_range)
            self._bar_cache.append_bars(fetched_bars)
        return self._bar_cache.read_bars(request)

    async def get_quote(self, security_id: str) -> Quote:
        quote = await self._provider.get_quote(security_id)
        key = (security_id,)
        self._set_state(key, self._state_for(key).with_quote(quote))
        return quote

    def realtime_state(self, security_ids: Sequence[str]) -> RealtimeSubscriptionState:
        return self._state_for(self._state_key(security_ids))

    def realtime_health(self, security_ids: Sequence[str], now: datetime) -> DataHealth:
        return self.realtime_state(security_ids).as_data_health(now, self._quote_stale_after)

    async def subscribe_quotes(
        self,
        security_ids: Sequence[str],
        *,
        max_reconnect_attempts: int = 3,
    ) -> AsyncGenerator[Quote, None]:
        key = self._state_key(security_ids)
        self._set_state(key, self._state_for(key).with_status(RealtimeConnectionStatus.CONNECTING))
        attempts = 0

        try:
            while True:
                try:
                    stream = self._provider.subscribe_quotes(key)
                    async for quote in stream:
                        attempts = 0
                        self._set_state(key, self._state_for(key).with_quote(quote))
                        yield quote
                except asyncio.CancelledError:
                    self._set_state(
                        key,
                        self._state_for(key).with_status(
                            RealtimeConnectionStatus.CANCELLED,
                            last_error="Subscription task was cancelled.",
                        ),
                    )
                    raise
                except Exception as exc:
                    attempts += 1
                    if attempts > max_reconnect_attempts:
                        self._set_state(
                            key,
                            self._state_for(key).with_status(
                                RealtimeConnectionStatus.DISCONNECTED,
                                reconnect_attempts=attempts,
                                last_error=str(exc),
                            ),
                        )
                        raise DataUnavailable(
                            f"Realtime subscription failed after {attempts} attempts: {exc}"
                        ) from exc

                    backoff = self._backoff(attempts)
                    self._set_state(
                        key,
                        self._state_for(key).with_status(
                            RealtimeConnectionStatus.RECONNECTING,
                            reconnect_attempts=attempts,
                            backoff_seconds=backoff.total_seconds(),
                            last_error=str(exc),
                        ),
                    )
                    await asyncio.sleep(backoff.total_seconds())
                    self._set_state(
                        key,
                        self._state_for(key).with_status(RealtimeConnectionStatus.CONNECTING),
                    )
        finally:
            current = self._realtime_states.get(key)
            if current is not None and current.status is not RealtimeConnectionStatus.DISCONNECTED:
                self._set_state(
                    key,
                    current.with_status(
                        RealtimeConnectionStatus.CANCELLED,
                        last_error="Subscription stream was closed.",
                    ),
                )

    def _backoff(self, attempt: int) -> timedelta:
        seconds = self._reconnect_base_delay.total_seconds() * (2 ** (attempt - 1))
        capped = min(seconds, self._reconnect_max_delay.total_seconds())
        return timedelta(seconds=capped)

    def _state_key(self, security_ids: Sequence[str]) -> tuple[str, ...]:
        if not security_ids:
            raise ValueError("security_ids must not be empty")
        return tuple(security_ids)

    def _state_for(self, key: tuple[str, ...]) -> RealtimeSubscriptionState:
        state = self._realtime_states.get(key)
        if state is None:
            state = RealtimeSubscriptionState.idle(key)
            self._realtime_states[key] = state
        return state

    def _set_state(self, key: tuple[str, ...], state: RealtimeSubscriptionState) -> None:
        self._realtime_states[key] = state


__all__ = [
    "MarketDataGateway",
    "RealtimeConnectionStatus",
    "RealtimeSubscriptionState",
]
