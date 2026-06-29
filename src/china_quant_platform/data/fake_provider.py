"""Deterministic fake market data provider for contract and integration tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, date, datetime, time, timedelta

from china_quant_platform.data.provider import (
    BarsRequest,
    CorporateActionRequest,
    FundNavRequest,
    MarketDataProvider,
    ProviderCapabilities,
    ProviderCapability,
)
from china_quant_platform.data.rate_limit import AsyncRateLimiter
from china_quant_platform.domain import (
    AssetType,
    Bar,
    BarInterval,
    CorporateAction,
    CorporateActionType,
    Currency,
    Exchange,
    FundNav,
    Quote,
    RecordQualityStatus,
    SecurityRef,
    SecurityStatus,
)

DEFAULT_FAKE_CAPABILITIES = frozenset(
    {
        ProviderCapability.SECURITY_SEARCH,
        ProviderCapability.REALTIME_QUOTE,
        ProviderCapability.REALTIME_SUBSCRIPTION,
        ProviderCapability.HISTORICAL_BARS,
        ProviderCapability.CORPORATE_ACTIONS,
        ProviderCapability.FUND_NAV,
    }
)


class DeterministicFakeMarketDataProvider(MarketDataProvider):
    """Provider with stable fixture data and no external I/O."""

    def __init__(
        self,
        *,
        provider_id: str = "deterministic_fake",
        capabilities: frozenset[ProviderCapability] = DEFAULT_FAKE_CAPABILITIES,
        limiter: AsyncRateLimiter | None = None,
        operation_delay_seconds: float = 0,
    ) -> None:
        self._provider_id = provider_id
        self._capabilities = ProviderCapabilities(
            provider_id=provider_id,
            supported=capabilities,
        )
        self._limiter = limiter
        self._operation_delay_seconds = operation_delay_seconds
        self._securities = self._build_security_fixtures()
        self._corporate_actions = self._build_corporate_actions()

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def search_security(self, keyword: str) -> list[SecurityRef]:
        await self._before_call(ProviderCapability.SECURITY_SEARCH)
        normalized = keyword.strip().lower()
        if not normalized:
            return []

        matches = [
            security
            for security in self._securities.values()
            if normalized in security.security_id.lower()
            or normalized in security.symbol.lower()
            or normalized in security.name.lower()
            or any(normalized in alias.lower() for alias in security.aliases)
        ]
        return sorted(matches, key=lambda security: security.security_id)

    async def get_quote(self, security_id: str) -> Quote:
        await self._before_call(ProviderCapability.REALTIME_QUOTE)
        self._require_security(security_id)
        source_time = self._session_datetime(date(2026, 6, 26), time(14, 59))
        base = self._base_price(security_id)
        return Quote(
            security_id=security_id,
            latest_price=base + 1.2,
            previous_close=base,
            open_price=base + 0.4,
            high_price=base + 1.8,
            low_price=base - 0.6,
            volume=100_000 + self._stable_offset(security_id),
            amount=(base + 1.2) * 100_000,
            bid_price=base + 1.19,
            ask_price=base + 1.21,
            provider=self.provider_id,
            schema_version="fake.v1",
            source_time=source_time,
            observed_at=source_time,
            received_at=source_time + timedelta(seconds=1),
            quality_status=RecordQualityStatus.OK,
        )

    async def get_bars(self, request: BarsRequest) -> list[Bar]:
        await self._before_call(ProviderCapability.HISTORICAL_BARS)
        if request.interval is not BarInterval.DAILY:
            self.capabilities.require(ProviderCapability.MINUTE_BARS)
        self._require_security(request.security_id)

        bars: list[Bar] = []
        current_date = request.start_time.date()
        while current_date <= request.end_time.date():
            if current_date.weekday() < 5:
                start_time = self._session_datetime(current_date, time(9, 30))
                end_time = self._session_datetime(current_date, time(15, 0))
                if start_time >= request.start_time and end_time <= request.end_time:
                    bars.append(self._bar_for_date(request, current_date, start_time, end_time))
            current_date += timedelta(days=1)
        return bars

    async def _quote_stream(self, security_ids: Sequence[str]) -> AsyncIterator[Quote]:
        self.capabilities.require(ProviderCapability.REALTIME_SUBSCRIPTION)
        for security_id in security_ids:
            self._require_security(security_id)

        index = 0
        while True:
            await self._before_call(ProviderCapability.REALTIME_SUBSCRIPTION)
            security_id = security_ids[index % len(security_ids)]
            quote = await self.get_quote(security_id)
            yield quote
            index += 1

    def subscribe_quotes(self, security_ids: Sequence[str]) -> AsyncIterator[Quote]:
        if not security_ids:
            raise ValueError("security_ids must not be empty")
        return self._quote_stream(tuple(security_ids))

    async def get_corporate_actions(
        self,
        request: CorporateActionRequest,
    ) -> list[CorporateAction]:
        await self._before_call(ProviderCapability.CORPORATE_ACTIONS)
        self._require_security(request.security_id)
        return [
            action
            for action in self._corporate_actions.get(request.security_id, ())
            if action.ex_date is not None
            and request.start_date <= action.ex_date <= request.end_date
        ]

    async def get_fund_nav(self, request: FundNavRequest) -> list[FundNav]:
        await self._before_call(ProviderCapability.FUND_NAV)
        self._require_security(request.fund_id)
        security = self._securities[request.fund_id]
        if security.asset_type is not AssetType.MUTUAL_FUND:
            return []

        navs: list[FundNav] = []
        current_date = request.start_date
        while current_date <= request.end_date:
            if current_date.weekday() < 5:
                published_at = self._session_datetime(current_date, time(20, 0))
                navs.append(
                    FundNav(
                        fund_id=request.fund_id,
                        nav_date=current_date,
                        unit_nav=1.0 + (current_date.toordinal() % 17) / 100,
                        accumulated_nav=2.0 + (current_date.toordinal() % 23) / 100,
                        published_at=published_at,
                        provider=self.provider_id,
                        schema_version="fake.v1",
                        source_time=published_at,
                        observed_at=published_at,
                        received_at=published_at + timedelta(seconds=1),
                        quality_status=RecordQualityStatus.OK,
                    )
                )
            current_date += timedelta(days=1)
        return navs

    async def _before_call(self, capability: ProviderCapability) -> None:
        self.capabilities.require(capability)
        if self._limiter is not None:
            await self._limiter.acquire()
        if self._operation_delay_seconds > 0:
            await asyncio.sleep(self._operation_delay_seconds)

    def _bar_for_date(
        self,
        request: BarsRequest,
        current_date: date,
        start_time: datetime,
        end_time: datetime,
    ) -> Bar:
        offset = current_date.toordinal() % 11
        base = self._base_price(request.security_id) + offset
        return Bar(
            security_id=request.security_id,
            interval=request.interval,
            start_time=start_time,
            end_time=end_time,
            trade_date=current_date,
            open_price=base,
            high_price=base + 2,
            low_price=base - 1,
            close_price=base + 1,
            volume=50_000 + offset * 100,
            amount=(base + 1) * 50_000,
            adjustment=request.adjustment,
            provider=self.provider_id,
            schema_version="fake.v1",
            source_time=end_time,
            observed_at=end_time,
            received_at=end_time + timedelta(seconds=1),
            quality_status=RecordQualityStatus.OK,
        )

    def _require_security(self, security_id: str) -> None:
        if security_id not in self._securities:
            raise KeyError(f"Unknown fake security_id: {security_id}")

    def _base_price(self, security_id: str) -> float:
        return 10.0 + self._stable_offset(security_id) % 200

    @staticmethod
    def _stable_offset(value: str) -> int:
        return sum(ord(character) for character in value)

    @staticmethod
    def _session_datetime(day: date, session_time: time) -> datetime:
        return datetime.combine(day, session_time, tzinfo=UTC)

    @staticmethod
    def _build_security_fixtures() -> dict[str, SecurityRef]:
        securities = (
            SecurityRef(
                security_id="SSE:600519",
                symbol="600519",
                name="贵州茅台",
                asset_type=AssetType.STOCK,
                exchange=Exchange.SSE,
                currency=Currency.CNY,
                listed_date=date(2001, 8, 27),
                status_date=date(2026, 6, 28),
                status=SecurityStatus.ACTIVE,
                aliases=("Kweichow Moutai", "茅台"),
            ),
            SecurityRef(
                security_id="SSE:510300",
                symbol="510300",
                name="沪深300ETF",
                asset_type=AssetType.ETF,
                exchange=Exchange.SSE,
                currency=Currency.CNY,
                listed_date=date(2012, 5, 28),
                status_date=date(2026, 6, 28),
                status=SecurityStatus.ACTIVE,
                aliases=("CSI300 ETF", "300ETF"),
            ),
            SecurityRef(
                security_id="FUND:000001",
                symbol="000001",
                name="华夏成长混合",
                asset_type=AssetType.MUTUAL_FUND,
                exchange=Exchange.FUND_COMPANY,
                currency=Currency.CNY,
                listed_date=date(2001, 12, 18),
                status_date=date(2026, 6, 28),
                status=SecurityStatus.ACTIVE,
                aliases=("Huaxia Growth",),
            ),
        )
        return {security.security_id: security for security in securities}

    def _build_corporate_actions(self) -> dict[str, tuple[CorporateAction, ...]]:
        action_time = self._session_datetime(date(2026, 6, 1), time(19, 0))
        return {
            "SSE:600519": (
                CorporateAction(
                    security_id="SSE:600519",
                    action_type=CorporateActionType.DIVIDEND,
                    announcement_time=action_time,
                    ex_date=date(2026, 6, 5),
                    record_date=date(2026, 6, 4),
                    payment_date=date(2026, 6, 8),
                    cash_amount=2.5,
                    share_ratio=None,
                    provider=self.provider_id,
                    schema_version="fake.v1",
                    source_time=action_time,
                    observed_at=action_time,
                    received_at=action_time + timedelta(seconds=1),
                    quality_status=RecordQualityStatus.OK,
                ),
            )
        }


__all__ = ["DEFAULT_FAKE_CAPABILITIES", "DeterministicFakeMarketDataProvider"]
