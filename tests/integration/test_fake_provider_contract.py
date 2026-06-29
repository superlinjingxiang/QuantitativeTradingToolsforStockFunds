"""Contract tests for deterministic fake market data provider."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from china_quant_platform.data import (
    BarsRequest,
    DeterministicFakeMarketDataProvider,
    FundNavRequest,
    MarketDataProvider,
    ProviderCapability,
)
from china_quant_platform.domain import (
    AssetType,
    BarInterval,
    DataUnavailable,
    Exchange,
    FundNav,
    Quote,
    SecurityRef,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def aware_datetime(month: int, day: int, hour: int = 9, minute: int = 30) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


def test_fake_provider_satisfies_protocol_at_runtime() -> None:
    provider = DeterministicFakeMarketDataProvider()

    assert isinstance(provider, MarketDataProvider)
    assert provider.capabilities.supports(ProviderCapability.SECURITY_SEARCH)
    assert provider.capabilities.supports(ProviderCapability.HISTORICAL_BARS)


def test_fake_provider_search_is_deterministic_and_typed() -> None:
    async def run_scenario() -> tuple[list[SecurityRef], list[SecurityRef]]:
        provider = DeterministicFakeMarketDataProvider()
        return await provider.search_security("茅台"), await provider.search_security("茅台")

    first, second = asyncio.run(run_scenario())

    assert first == second
    assert first[0].security_id == "SSE:600519"
    assert first[0].asset_type is AssetType.STOCK
    assert first[0].exchange is Exchange.SSE


def test_fake_provider_quote_is_deterministic_and_source_stamped() -> None:
    async def run_scenario() -> tuple[Quote, Quote]:
        provider = DeterministicFakeMarketDataProvider()
        return await provider.get_quote("SSE:600519"), await provider.get_quote("SSE:600519")

    first, second = asyncio.run(run_scenario())

    assert first == second
    assert first.provider == "deterministic_fake"
    assert first.received_at >= first.source_time


def test_fake_provider_daily_bars_are_deterministic_and_exclude_weekends() -> None:
    async def run_scenario() -> int:
        provider = DeterministicFakeMarketDataProvider()
        bars = await provider.get_bars(
            BarsRequest(
                security_id="SSE:600519",
                interval=BarInterval.DAILY,
                start_time=aware_datetime(6, 22),
                end_time=aware_datetime(6, 28, 16, 0),
            )
        )
        return len(bars)

    assert asyncio.run(run_scenario()) == 5


def test_fake_provider_reports_unsupported_minute_bars_as_typed_error() -> None:
    async def run_scenario() -> None:
        provider = DeterministicFakeMarketDataProvider()
        await provider.get_bars(
            BarsRequest(
                security_id="SSE:600519",
                interval=BarInterval.ONE_MINUTE,
                start_time=aware_datetime(6, 26),
                end_time=aware_datetime(6, 26, 16, 0),
            )
        )

    with pytest.raises(DataUnavailable) as error:
        asyncio.run(run_scenario())

    assert error.value.blocks_signal is True
    assert error.value.retryable is False


def test_fake_provider_subscribe_quotes_streams_typed_quotes() -> None:
    async def run_scenario() -> list[Quote]:
        provider = DeterministicFakeMarketDataProvider()
        stream = provider.subscribe_quotes(["SSE:600519", "SSE:510300"])
        return [await anext(stream), await anext(stream)]

    quotes = asyncio.run(run_scenario())

    assert [quote.security_id for quote in quotes] == ["SSE:600519", "SSE:510300"]


def test_fake_provider_fund_nav_returns_official_nav_only() -> None:
    async def run_scenario() -> list[FundNav]:
        provider = DeterministicFakeMarketDataProvider()
        return await provider.get_fund_nav(
            FundNavRequest(
                fund_id="FUND:000001",
                start_date=aware_datetime(6, 22).date(),
                end_date=aware_datetime(6, 28).date(),
            )
        )

    navs = asyncio.run(run_scenario())

    assert len(navs) == 5
    assert all(isinstance(nav, FundNav) for nav in navs)


def test_fake_provider_operations_are_cancellable() -> None:
    async def run_scenario() -> None:
        provider = DeterministicFakeMarketDataProvider(operation_delay_seconds=60)
        task = asyncio.create_task(provider.get_quote("SSE:600519"))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run_scenario())


def test_domain_layer_does_not_depend_on_provider_layer() -> None:
    domain_files = (PROJECT_ROOT / "src" / "china_quant_platform" / "domain").glob("*.py")

    for path in domain_files:
        assert "china_quant_platform.data" not in path.read_text(encoding="utf-8")
