"""Official-NAV-only off-exchange fund confirmation and risk analysis."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from enum import StrEnum

from pydantic import AwareDatetime, Field, model_validator

from china_quant_platform.domain import EstimatedFundNav, FundNav
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import NonEmptyString, SecurityId


class FundOrderType(StrEnum):
    SUBSCRIBE = "SUBSCRIBE"
    REDEEM = "REDEEM"


class FundRiskLevel(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class FundFeeSchedule(DomainModel):
    subscription_fee_rate: float = Field(default=0.0, ge=0, le=1)
    redemption_fee_rate: float = Field(default=0.0, ge=0, le=1)
    management_fee_rate_annual: float = Field(default=0.0, ge=0, le=1)
    custody_fee_rate_annual: float = Field(default=0.0, ge=0, le=1)

    @property
    def ongoing_fee_rate_annual(self) -> float:
        return self.management_fee_rate_annual + self.custody_fee_rate_annual


class FundConfirmationRule(DomainModel):
    cutoff_time: time = time(15, 0)
    confirmation_days: int = Field(default=1, ge=0)
    settlement_days: int = Field(default=1, ge=0)


class FundOrderRequest(DomainModel):
    fund_id: SecurityId
    order_type: FundOrderType
    submitted_at: AwareDatetime
    amount: float | None = Field(default=None, gt=0)
    shares: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_amount_or_shares(self) -> FundOrderRequest:
        if self.order_type is FundOrderType.SUBSCRIBE and self.amount is None:
            raise ValueError("subscription orders require amount")
        if self.order_type is FundOrderType.REDEEM and self.shares is None:
            raise ValueError("redemption orders require shares")
        return self


class FundConfirmation(DomainModel):
    fund_id: SecurityId
    order_type: FundOrderType
    submitted_at: AwareDatetime
    effective_nav_date: date
    confirmed_at: AwareDatetime
    settlement_date: date
    official_unit_nav: float = Field(gt=0)
    fee: float = Field(ge=0)
    confirmed_shares: float | None = Field(default=None, gt=0)
    confirmed_cash_amount: float | None = Field(default=None, ge=0)
    note: NonEmptyString


class FundAnalysisReport(DomainModel):
    fund_id: SecurityId
    as_of: date
    nav_count: int = Field(ge=2)
    latest_official_nav: float = Field(gt=0)
    weekly_return: float
    monthly_return: float
    max_drawdown: float = Field(ge=0)
    volatility: float = Field(ge=0)
    risk_adjusted_return: float | None = None
    benchmark_return: float | None = None
    excess_return: float | None = None
    fee_drag_estimate: float = Field(ge=0)
    risk_level: FundRiskLevel
    warnings: tuple[NonEmptyString, ...] = ()


def confirm_fund_order(
    *,
    order: FundOrderRequest,
    navs: Sequence[FundNav | EstimatedFundNav],
    fee_schedule: FundFeeSchedule,
    confirmation_rule: FundConfirmationRule | None = None,
) -> FundConfirmation:
    official_navs = _official_navs_for_fund(navs, order.fund_id)
    rule = confirmation_rule or FundConfirmationRule()
    target_date = _target_nav_date(order.submitted_at, rule.cutoff_time)
    nav = _first_nav_on_or_after(official_navs, target_date)
    confirmed_at = _at_market_time(nav.published_at, rule.confirmation_days)
    settlement_date = confirmed_at.date() + timedelta(days=rule.settlement_days)

    if order.order_type is FundOrderType.SUBSCRIBE:
        assert order.amount is not None
        fee = order.amount * fee_schedule.subscription_fee_rate
        confirmed_shares = (order.amount - fee) / nav.unit_nav
        return FundConfirmation(
            fund_id=order.fund_id,
            order_type=order.order_type,
            submitted_at=order.submitted_at,
            effective_nav_date=nav.nav_date,
            confirmed_at=confirmed_at,
            settlement_date=settlement_date,
            official_unit_nav=nav.unit_nav,
            fee=fee,
            confirmed_shares=confirmed_shares,
            note="Confirmed with official NAV; estimated intraday NAV was not used.",
        )

    assert order.shares is not None
    gross_amount = order.shares * nav.unit_nav
    fee = gross_amount * fee_schedule.redemption_fee_rate
    return FundConfirmation(
        fund_id=order.fund_id,
        order_type=order.order_type,
        submitted_at=order.submitted_at,
        effective_nav_date=nav.nav_date,
        confirmed_at=confirmed_at,
        settlement_date=settlement_date,
        official_unit_nav=nav.unit_nav,
        fee=fee,
        confirmed_shares=order.shares,
        confirmed_cash_amount=gross_amount - fee,
        note="Redeemed with official NAV; estimated intraday NAV was not used.",
    )


def analyze_off_exchange_fund(
    *,
    fund_id: SecurityId,
    navs: Sequence[FundNav | EstimatedFundNav],
    fee_schedule: FundFeeSchedule,
    benchmark_navs: Sequence[FundNav | EstimatedFundNav] = (),
) -> FundAnalysisReport:
    official_navs = _official_navs_for_fund(navs, fund_id)
    if len(official_navs) < 2:
        raise ValueError("fund analysis requires at least two official NAV records")

    latest = official_navs[-1]
    returns = _periodic_returns(official_navs)
    weekly_return = _window_return(official_navs, days=7)
    monthly_return = _window_return(official_navs, days=30)
    max_drawdown = _max_drawdown(tuple(nav.unit_nav for nav in official_navs))
    volatility = statistics.pstdev(returns) if len(returns) > 1 else 0.0
    risk_adjusted = (statistics.fmean(returns) / volatility) if volatility > 0 else None
    benchmark_return = None
    excess_return = None
    warnings: list[str] = []
    if benchmark_navs:
        benchmark_official = _official_navs_for_fund(benchmark_navs, benchmark_navs[0].fund_id)
        if len(benchmark_official) >= 2:
            benchmark_return = _window_return(benchmark_official, days=30)
            excess_return = monthly_return - benchmark_return
        else:
            warnings.append("Benchmark comparison skipped because official NAV history is short.")

    return FundAnalysisReport(
        fund_id=fund_id,
        as_of=latest.nav_date,
        nav_count=len(official_navs),
        latest_official_nav=latest.unit_nav,
        weekly_return=weekly_return,
        monthly_return=monthly_return,
        max_drawdown=max_drawdown,
        volatility=volatility,
        risk_adjusted_return=risk_adjusted,
        benchmark_return=benchmark_return,
        excess_return=excess_return,
        fee_drag_estimate=fee_schedule.ongoing_fee_rate_annual / 12.0,
        risk_level=_risk_level(max_drawdown=max_drawdown, volatility=volatility),
        warnings=tuple(warnings),
    )


def _official_navs_for_fund(
    navs: Sequence[FundNav | EstimatedFundNav],
    fund_id: str,
) -> tuple[FundNav, ...]:
    official: list[FundNav] = []
    for nav in navs:
        if isinstance(nav, EstimatedFundNav):
            raise ValueError("EstimatedFundNav cannot be used for official fund analysis")
        if nav.fund_id == fund_id:
            official.append(nav)
    if not official:
        raise ValueError(f"No official NAV records for fund_id {fund_id}")
    return tuple(sorted(official, key=lambda item: item.nav_date))


def _target_nav_date(submitted_at: datetime, cutoff_time: time) -> date:
    if submitted_at.timetz().replace(tzinfo=None) <= cutoff_time:
        return submitted_at.date()
    return submitted_at.date() + timedelta(days=1)


def _first_nav_on_or_after(navs: tuple[FundNav, ...], target_date: date) -> FundNav:
    for nav in navs:
        if nav.nav_date >= target_date:
            return nav
    raise ValueError(f"No official NAV on or after {target_date}")


def _at_market_time(published_at: datetime, days: int) -> datetime:
    return published_at + timedelta(days=days)


def _periodic_returns(navs: tuple[FundNav, ...]) -> tuple[float, ...]:
    return tuple(
        navs[index].unit_nav / navs[index - 1].unit_nav - 1.0 for index in range(1, len(navs))
    )


def _window_return(navs: tuple[FundNav, ...], *, days: int) -> float:
    end = navs[-1]
    start_cutoff = end.nav_date - timedelta(days=days)
    candidates = tuple(nav for nav in navs if nav.nav_date <= start_cutoff)
    start = candidates[-1] if candidates else navs[0]
    return end.unit_nav / start.unit_nav - 1.0


def _max_drawdown(values: tuple[float, ...]) -> float:
    peak = values[0]
    drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            drawdown = max(drawdown, 1.0 - value / peak)
    return drawdown


def _risk_level(*, max_drawdown: float, volatility: float) -> FundRiskLevel:
    if max_drawdown >= 0.15 or volatility >= 0.04:
        return FundRiskLevel.HIGH
    if max_drawdown <= 0.03 and volatility <= 0.01:
        return FundRiskLevel.LOW
    return FundRiskLevel.NORMAL
