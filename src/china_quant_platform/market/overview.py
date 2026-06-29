"""Market overview snapshots built from standardized quotes."""

from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, Field

from china_quant_platform.domain import DataHealth, DataHealthStatus, Quote
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import NonEmptyString, SecurityId


class MarketVolatilityState(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class MarketTrendState(StrEnum):
    RISK_ON = "RISK_ON"
    BALANCED = "BALANCED"
    RISK_OFF = "RISK_OFF"


class IndexSnapshot(DomainModel):
    security_id: SecurityId
    name: NonEmptyString
    latest_value: float = Field(ge=0)
    change_pct: float
    turnover: float = Field(ge=0)
    source_time: AwareDatetime

    @classmethod
    def from_quote(
        cls,
        quote: Quote,
        *,
        name: NonEmptyString | None = None,
    ) -> IndexSnapshot:
        change_pct = _change_pct(quote.latest_price, quote.previous_close)
        return cls(
            security_id=quote.security_id,
            name=name or quote.security_id,
            latest_value=quote.latest_price,
            change_pct=change_pct,
            turnover=quote.amount,
            source_time=quote.source_time,
        )


class MarketBreadth(DomainModel):
    advancers: int = Field(ge=0)
    decliners: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    total_turnover: float = Field(ge=0)
    average_change_pct: float
    average_abs_change_pct: float = Field(ge=0)
    volatility_state: MarketVolatilityState
    trend_state: MarketTrendState

    @property
    def total_count(self) -> int:
        return self.advancers + self.decliners + self.unchanged

    @property
    def advance_decline_ratio(self) -> float:
        directional = self.advancers + self.decliners
        if directional == 0:
            return 0.0
        return self.advancers / directional


class MarketOverview(DomainModel):
    as_of: AwareDatetime
    indices: tuple[IndexSnapshot, ...]
    breadth: MarketBreadth
    data_health: DataHealth


def build_market_overview(
    *,
    index_quotes: tuple[Quote, ...],
    constituent_quotes: tuple[Quote, ...],
    as_of: AwareDatetime,
    index_names: dict[str, str] | None = None,
    stale_after_seconds: int = 300,
) -> MarketOverview:
    names = index_names or {}
    indices = tuple(
        IndexSnapshot.from_quote(quote, name=names.get(quote.security_id))
        for quote in sorted(index_quotes, key=lambda item: item.security_id)
    )
    breadth = _market_breadth(constituent_quotes)
    health = _overview_health(
        as_of=as_of,
        quotes=(*index_quotes, *constituent_quotes),
        stale_after_seconds=stale_after_seconds,
    )
    return MarketOverview(as_of=as_of, indices=indices, breadth=breadth, data_health=health)


def _market_breadth(quotes: tuple[Quote, ...]) -> MarketBreadth:
    if not quotes:
        return MarketBreadth(
            advancers=0,
            decliners=0,
            unchanged=0,
            total_turnover=0.0,
            average_change_pct=0.0,
            average_abs_change_pct=0.0,
            volatility_state=MarketVolatilityState.NORMAL,
            trend_state=MarketTrendState.BALANCED,
        )
    changes = tuple(_change_pct(quote.latest_price, quote.previous_close) for quote in quotes)
    advancers = sum(1 for change in changes if change > 0)
    decliners = sum(1 for change in changes if change < 0)
    unchanged = len(changes) - advancers - decliners
    average_change = sum(changes) / len(changes)
    average_abs_change = sum(abs(change) for change in changes) / len(changes)
    return MarketBreadth(
        advancers=advancers,
        decliners=decliners,
        unchanged=unchanged,
        total_turnover=sum(quote.amount for quote in quotes),
        average_change_pct=average_change,
        average_abs_change_pct=average_abs_change,
        volatility_state=_volatility_state(average_abs_change),
        trend_state=_trend_state(advancers, decliners, average_change),
    )


def _change_pct(latest: float, previous_close: float) -> float:
    if previous_close <= 0:
        return 0.0
    return latest / previous_close - 1.0


def _volatility_state(average_abs_change_pct: float) -> MarketVolatilityState:
    if average_abs_change_pct >= 0.03:
        return MarketVolatilityState.HIGH
    if average_abs_change_pct <= 0.005:
        return MarketVolatilityState.LOW
    return MarketVolatilityState.NORMAL


def _trend_state(
    advancers: int,
    decliners: int,
    average_change_pct: float,
) -> MarketTrendState:
    directional = advancers + decliners
    if directional == 0:
        return MarketTrendState.BALANCED
    advance_ratio = advancers / directional
    if advance_ratio >= 0.60 and average_change_pct >= 0:
        return MarketTrendState.RISK_ON
    if advance_ratio <= 0.40 and average_change_pct < 0:
        return MarketTrendState.RISK_OFF
    return MarketTrendState.BALANCED


def _overview_health(
    *,
    as_of: AwareDatetime,
    quotes: tuple[Quote, ...],
    stale_after_seconds: int,
) -> DataHealth:
    if not quotes:
        return DataHealth(
            status=DataHealthStatus.DEGRADED,
            block_signal=False,
            as_of=as_of,
            issues=("market overview has no quotes",),
        )
    stale_quotes = tuple(
        quote.security_id
        for quote in quotes
        if (as_of - quote.source_time).total_seconds() > stale_after_seconds
    )
    if stale_quotes:
        return DataHealth(
            status=DataHealthStatus.STALE,
            block_signal=True,
            as_of=as_of,
            issues=(f"stale market quotes: {', '.join(stale_quotes)}",),
        )
    return DataHealth(status=DataHealthStatus.HEALTHY, block_signal=False, as_of=as_of)
