"""Integration tests for provider-independent market data gateway behavior."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from china_quant_platform.data import (
    BarsRequest,
    DeterministicFakeMarketDataProvider,
    HistoricalBarCache,
    MarketDataGateway,
    RealtimeConnectionStatus,
)
from china_quant_platform.domain import Bar, BarInterval, DataHealthStatus, Quote


def aware_datetime(day: int, hour: int = 9, minute: int = 30) -> datetime:
    return datetime(2026, 6, day, hour, minute, tzinfo=UTC)


def daily_request(start_day: int, end_day: int) -> BarsRequest:
    return BarsRequest(
        security_id="SSE:600519",
        interval=BarInterval.DAILY,
        start_time=aware_datetime(start_day, 9, 30),
        end_time=aware_datetime(end_day, 16, 0),
    )


class CountingFakeProvider(DeterministicFakeMarketDataProvider):
    def __init__(self) -> None:
        super().__init__()
        self.bar_requests: list[BarsRequest] = []

    async def get_bars(self, request: BarsRequest) -> list[Bar]:
        self.bar_requests.append(request)
        return await super().get_bars(request)


class FlakySubscriptionProvider(DeterministicFakeMarketDataProvider):
    def __init__(self) -> None:
        super().__init__()
        self.subscription_attempts = 0

    def subscribe_quotes(self, security_ids: Sequence[str]) -> AsyncIterator[Quote]:
        self.subscription_attempts += 1
        if self.subscription_attempts == 1:
            return self._failing_stream()
        return super().subscribe_quotes(security_ids)

    async def _failing_stream(self) -> AsyncIterator[Quote]:
        if False:
            yield await self.get_quote("SSE:600519")
        raise ConnectionError("simulated realtime disconnect")


def test_gateway_fills_cache_incrementally_without_full_refresh(tmp_path: Path) -> None:
    async def run_scenario() -> tuple[list[Bar], list[BarsRequest]]:
        provider = CountingFakeProvider()
        gateway = MarketDataGateway(provider, HistoricalBarCache(tmp_path))

        first_request = daily_request(22, 24)
        first_bars = await gateway.get_bars(first_request)
        second_bars = await gateway.get_bars(first_request)
        extended_bars = await gateway.get_bars(daily_request(22, 26))

        assert first_bars == second_bars
        assert len(extended_bars) == 5
        return extended_bars, provider.bar_requests

    bars, requests = asyncio.run(run_scenario())

    assert [bar.trade_date for bar in bars] == [
        date(2026, 6, 22),
        date(2026, 6, 23),
        date(2026, 6, 24),
        date(2026, 6, 25),
        date(2026, 6, 26),
    ]
    assert len(requests) == 2
    assert requests[0].start_time.date() == date(2026, 6, 22)
    assert requests[0].end_time.date() == date(2026, 6, 24)
    assert requests[1].start_time.date() == date(2026, 6, 25)
    assert requests[1].end_time.date() == date(2026, 6, 26)


def test_gateway_marks_stale_realtime_quote_as_blocking(tmp_path: Path) -> None:
    async def run_scenario() -> DataHealthStatus:
        provider = DeterministicFakeMarketDataProvider()
        gateway = MarketDataGateway(
            provider,
            HistoricalBarCache(tmp_path),
            quote_stale_after=timedelta(seconds=5),
        )
        quote = await gateway.get_quote("SSE:600519")
        health = gateway.realtime_health(
            ["SSE:600519"],
            quote.source_time + timedelta(seconds=6),
        )
        assert health.block_signal is True
        return health.status

    assert asyncio.run(run_scenario()) is DataHealthStatus.STALE


def test_gateway_realtime_subscription_updates_state_and_closes(tmp_path: Path) -> None:
    async def run_scenario() -> RealtimeConnectionStatus:
        provider = DeterministicFakeMarketDataProvider()
        gateway = MarketDataGateway(provider, HistoricalBarCache(tmp_path))
        stream = gateway.subscribe_quotes(["SSE:600519"])

        quote = await anext(stream)
        assert quote.security_id == "SSE:600519"
        assert gateway.realtime_state(["SSE:600519"]).status is RealtimeConnectionStatus.CONNECTED

        await stream.aclose()
        return gateway.realtime_state(["SSE:600519"]).status

    assert asyncio.run(run_scenario()) is RealtimeConnectionStatus.CANCELLED


def test_gateway_reconnects_realtime_subscription_after_disconnect(tmp_path: Path) -> None:
    async def run_scenario() -> tuple[int, RealtimeConnectionStatus]:
        provider = FlakySubscriptionProvider()
        gateway = MarketDataGateway(
            provider,
            HistoricalBarCache(tmp_path),
            reconnect_base_delay=timedelta(seconds=0),
            reconnect_max_delay=timedelta(seconds=0),
        )
        stream = gateway.subscribe_quotes(["SSE:600519"], max_reconnect_attempts=1)

        quote = await anext(stream)
        assert quote.security_id == "SSE:600519"
        status = gateway.realtime_state(["SSE:600519"]).status
        await stream.aclose()
        return provider.subscription_attempts, status

    attempts, status = asyncio.run(run_scenario())

    assert attempts == 2
    assert status is RealtimeConnectionStatus.CONNECTED
