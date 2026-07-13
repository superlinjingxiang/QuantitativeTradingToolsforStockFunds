"""Multi-source provider routing tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

import pytest

from china_quant_platform.data import (
    BarsRequest,
    CorporateActionRequest,
    DeterministicFakeMarketDataProvider,
    FundNavRequest,
    MultiSourceMarketDataProvider,
    ProviderCapabilities,
    ProviderCapability,
    create_default_market_data_provider,
)
from china_quant_platform.domain import (
    Bar,
    CorporateAction,
    DataUnavailable,
    FundNav,
    Quote,
    SecurityRef,
)


class FailingMarketDataProvider:
    provider_id = "failing"
    capabilities = ProviderCapabilities(
        provider_id=provider_id,
        supported=frozenset(
            {
                ProviderCapability.SECURITY_SEARCH,
                ProviderCapability.REALTIME_QUOTE,
                ProviderCapability.HISTORICAL_BARS,
            }
        ),
    )

    async def search_security(self, keyword: str) -> list[SecurityRef]:
        raise DataUnavailable(f"search failed for {keyword}")

    async def get_quote(self, security_id: str) -> Quote:
        raise DataUnavailable(f"quote failed for {security_id}")

    async def get_bars(self, request: BarsRequest) -> list[Bar]:
        raise DataUnavailable(f"bars failed for {request.security_id}")

    def subscribe_quotes(self, security_ids: Sequence[str]) -> AsyncIterator[Quote]:
        raise DataUnavailable(f"subscription failed for {security_ids!r}")

    async def get_corporate_actions(
        self,
        request: CorporateActionRequest,
    ) -> list[CorporateAction]:
        raise DataUnavailable("corporate actions failed")

    async def get_fund_nav(self, request: FundNavRequest) -> list[FundNav]:
        raise DataUnavailable("fund nav failed")


class EmptyBarsMarketDataProvider(FailingMarketDataProvider):
    provider_id = "empty"
    capabilities = ProviderCapabilities(
        provider_id=provider_id,
        supported=FailingMarketDataProvider.capabilities.supported,
    )

    async def get_bars(self, request: BarsRequest) -> list[Bar]:
        return []


def test_multi_source_falls_back_to_next_provider_for_quote() -> None:
    provider = MultiSourceMarketDataProvider(
        (FailingMarketDataProvider(), DeterministicFakeMarketDataProvider())
    )

    quote = asyncio.run(provider.get_quote("SSE:600519"))

    assert quote.provider == "deterministic_fake"


def test_multi_source_falls_back_when_provider_returns_empty_bars() -> None:
    provider = MultiSourceMarketDataProvider(
        (EmptyBarsMarketDataProvider(), DeterministicFakeMarketDataProvider())
    )
    request = BarsRequest.model_validate(
        {
            "security_id": "SSE:600519",
            "interval": "1d",
            "start_time": "2026-06-01T00:00:00Z",
            "end_time": "2026-07-01T00:00:00Z",
            "adjustment": "NONE",
        }
    )

    bars = asyncio.run(provider.get_bars(request))

    assert bars
    assert bars[0].provider == "deterministic_fake"


def test_multi_source_raises_combined_failure_when_all_sources_fail() -> None:
    provider = MultiSourceMarketDataProvider((FailingMarketDataProvider(),))

    with pytest.raises(DataUnavailable) as error:
        asyncio.run(provider.get_quote("SSE:600519"))

    assert "failing: quote failed" in error.value.engineering_message


def test_default_provider_uses_tonghuashun_first_when_token_is_configured() -> None:
    provider = create_default_market_data_provider(
        {"CQP_THS_IFIND_REFRESH_TOKEN": "refresh-token-fixture"}
    )

    assert isinstance(provider, MultiSourceMarketDataProvider)
    assert provider.providers[0].provider_id == "tonghuashun_ifind"


def test_default_provider_skips_tonghuashun_without_token() -> None:
    provider = create_default_market_data_provider({})

    assert isinstance(provider, MultiSourceMarketDataProvider)
    assert provider.providers[0].provider_id == "eastmoney"
