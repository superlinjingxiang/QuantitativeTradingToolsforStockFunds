"""Provider protocols and request contracts for market data access."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import date
from enum import StrEnum
from typing import Protocol, Self, runtime_checkable

from pydantic import AwareDatetime, Field, model_validator

from china_quant_platform.domain import (
    AdjustmentMode,
    Bar,
    BarInterval,
    CorporateAction,
    DataUnavailable,
    FundNav,
    Quote,
    SecurityRef,
)
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import NonEmptyString, SecurityId


class ProviderCapability(StrEnum):
    SECURITY_SEARCH = "SECURITY_SEARCH"
    REALTIME_QUOTE = "REALTIME_QUOTE"
    REALTIME_SUBSCRIPTION = "REALTIME_SUBSCRIPTION"
    HISTORICAL_BARS = "HISTORICAL_BARS"
    MINUTE_BARS = "MINUTE_BARS"
    CORPORATE_ACTIONS = "CORPORATE_ACTIONS"
    FUND_NAV = "FUND_NAV"


class ProviderCapabilities(DomainModel):
    provider_id: NonEmptyString
    supported: frozenset[ProviderCapability] = Field(default_factory=frozenset)

    def supports(self, capability: ProviderCapability) -> bool:
        return capability in self.supported

    def require(self, capability: ProviderCapability) -> None:
        if not self.supports(capability):
            raise DataUnavailable(
                f"Provider {self.provider_id!r} does not support {capability.value}",
                retryable=False,
            )


class BarsRequest(DomainModel):
    security_id: SecurityId
    interval: BarInterval
    start_time: AwareDatetime
    end_time: AwareDatetime
    adjustment: AdjustmentMode = AdjustmentMode.NONE

    @model_validator(mode="after")
    def end_time_must_be_after_start_time(self) -> Self:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time")
        return self


class CorporateActionRequest(DomainModel):
    security_id: SecurityId
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def end_date_must_not_precede_start_date(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be earlier than start_date")
        return self


class FundNavRequest(DomainModel):
    fund_id: SecurityId
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def end_date_must_not_precede_start_date(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be earlier than start_date")
        return self


@runtime_checkable
class MarketDataProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def search_security(self, keyword: str) -> list[SecurityRef]: ...

    async def get_quote(self, security_id: str) -> Quote: ...

    async def get_bars(self, request: BarsRequest) -> list[Bar]: ...

    def subscribe_quotes(self, security_ids: Sequence[str]) -> AsyncIterator[Quote]: ...

    async def get_corporate_actions(
        self,
        request: CorporateActionRequest,
    ) -> list[CorporateAction]: ...

    async def get_fund_nav(self, request: FundNavRequest) -> list[FundNav]: ...
