"""Priority-routed market data provider."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import TypeVar

from china_quant_platform.data.provider import (
    BarsRequest,
    CorporateActionRequest,
    FundNavRequest,
    MarketDataProvider,
    ProviderCapabilities,
    ProviderCapability,
)
from china_quant_platform.domain import (
    Bar,
    BarInterval,
    CorporateAction,
    DataUnavailable,
    FundNav,
    Quote,
    SecurityRef,
)

_T = TypeVar("_T")
_MINUTE_INTERVALS = frozenset(
    {
        BarInterval.TICK,
        BarInterval.ONE_MINUTE,
        BarInterval.FIVE_MINUTES,
        BarInterval.FIFTEEN_MINUTES,
        BarInterval.THIRTY_MINUTES,
        BarInterval.SIXTY_MINUTES,
    }
)


class MultiSourceMarketDataProvider(MarketDataProvider):
    """Route data requests across providers in priority order."""

    def __init__(
        self,
        providers: Sequence[MarketDataProvider],
        *,
        provider_id: str = "multi_source",
        poll_interval_seconds: float = 5.0,
    ) -> None:
        if not providers:
            raise ValueError("providers must not be empty")
        self._providers = tuple(providers)
        self._provider_id = provider_id
        self._poll_interval_seconds = poll_interval_seconds
        self._capabilities = ProviderCapabilities(
            provider_id=provider_id,
            supported=frozenset(
                capability
                for provider in self._providers
                for capability in provider.capabilities.supported
            ),
        )

    @property
    def providers(self) -> tuple[MarketDataProvider, ...]:
        return self._providers

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def search_security(self, keyword: str) -> list[SecurityRef]:
        self.capabilities.require(ProviderCapability.SECURITY_SEARCH)
        results: dict[str, SecurityRef] = {}
        failures: list[str] = []
        for provider in self._providers_for(ProviderCapability.SECURITY_SEARCH):
            try:
                for security in await provider.search_security(keyword):
                    results.setdefault(security.security_id, security)
            except DataUnavailable as exc:
                failures.append(_failure_text(provider.provider_id, exc))
        if results:
            return list(results.values())
        if failures:
            raise DataUnavailable("；".join(failures))
        return []

    async def get_quote(self, security_id: str) -> Quote:
        self.capabilities.require(ProviderCapability.REALTIME_QUOTE)
        return await self._first_success(
            ProviderCapability.REALTIME_QUOTE,
            lambda provider: provider.get_quote(security_id),
        )

    async def get_bars(self, request: BarsRequest) -> list[Bar]:
        self.capabilities.require(ProviderCapability.HISTORICAL_BARS)
        capability = (
            ProviderCapability.MINUTE_BARS
            if request.interval in _MINUTE_INTERVALS
            else ProviderCapability.HISTORICAL_BARS
        )
        failures: list[str] = []
        for provider in self._providers_for(capability):
            try:
                bars = await provider.get_bars(request)
            except DataUnavailable as exc:
                failures.append(_failure_text(provider.provider_id, exc))
                continue
            if bars:
                return bars
            failures.append(f"{provider.provider_id}: returned no bars")
        if failures:
            raise DataUnavailable("；".join(failures))
        raise DataUnavailable(
            f"No configured provider supports {capability.value}",
            retryable=False,
        )

    def subscribe_quotes(self, security_ids: Sequence[str]) -> AsyncIterator[Quote]:
        if not security_ids:
            raise ValueError("security_ids must not be empty")
        return self._poll_quotes(tuple(security_ids))

    async def get_corporate_actions(
        self,
        request: CorporateActionRequest,
    ) -> list[CorporateAction]:
        self.capabilities.require(ProviderCapability.CORPORATE_ACTIONS)
        return await self._first_success(
            ProviderCapability.CORPORATE_ACTIONS,
            lambda provider: provider.get_corporate_actions(request),
        )

    async def get_fund_nav(self, request: FundNavRequest) -> list[FundNav]:
        self.capabilities.require(ProviderCapability.FUND_NAV)
        return await self._first_success(
            ProviderCapability.FUND_NAV,
            lambda provider: provider.get_fund_nav(request),
        )

    async def _poll_quotes(self, security_ids: tuple[str, ...]) -> AsyncIterator[Quote]:
        while True:
            for security_id in security_ids:
                yield await self.get_quote(security_id)
            await asyncio.sleep(self._poll_interval_seconds)

    async def _first_success(
        self,
        capability: ProviderCapability,
        operation: Callable[[MarketDataProvider], Awaitable[_T]],
    ) -> _T:
        failures: list[str] = []
        for provider in self._providers_for(capability):
            try:
                return await operation(provider)
            except DataUnavailable as exc:
                failures.append(_failure_text(provider.provider_id, exc))
        if failures:
            raise DataUnavailable("；".join(failures))
        raise DataUnavailable(
            f"No configured provider supports {capability.value}",
            retryable=False,
        )

    def _providers_for(self, capability: ProviderCapability) -> tuple[MarketDataProvider, ...]:
        return tuple(
            provider for provider in self._providers if provider.capabilities.supports(capability)
        )


def _failure_text(provider_id: str, error: DataUnavailable) -> str:
    return f"{provider_id}: {error.engineering_message}"


__all__ = ["MultiSourceMarketDataProvider"]
