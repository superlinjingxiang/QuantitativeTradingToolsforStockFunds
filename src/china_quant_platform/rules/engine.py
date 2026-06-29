"""Effective-date China market rule resolution and validation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import StrEnum
from typing import Any

from china_quant_platform.domain import (
    AssetType,
    DataInvalid,
    EstimatedFundNav,
    Exchange,
    FundNav,
    RuleMissing,
    RuleReviewStatus,
    SecurityRef,
    SecurityRule,
)
from china_quant_platform.domain.base import DomainModel


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    SUBSCRIBE = "SUBSCRIBE"
    REDEEM = "REDEEM"


class PriceLimitBand(DomainModel):
    lower_price: float
    upper_price: float


class RuleValidationResult(DomainModel):
    allowed: bool
    reasons: tuple[str, ...] = ()


class FeeBreakdown(DomainModel):
    commission: float
    stamp_tax: float
    transfer_fee: float
    total: float


class RuleResolutionRequest(DomainModel):
    exchange: Exchange | str
    asset_type: AssetType | str
    trade_date: date
    security_id: str | None = None


class InMemoryRuleRepository:
    """Resolves approved rules by security, exchange, asset type, and date."""

    def __init__(self, rules: Sequence[SecurityRule]) -> None:
        self._rules = tuple(sorted(rules, key=lambda rule: rule.effective_from))

    def resolve(
        self,
        *,
        exchange: Exchange | str,
        asset_type: AssetType | str,
        trade_date: date,
        security_id: str | None = None,
    ) -> SecurityRule:
        request = RuleResolutionRequest(
            exchange=exchange,
            asset_type=asset_type,
            trade_date=trade_date,
            security_id=security_id,
        )
        candidates = [rule for rule in self._rules if _matches_rule(rule, request)]
        if not candidates:
            raise RuleMissing(
                "No approved market rule for "
                f"{_enum_value(exchange)} {_enum_value(asset_type)} {security_id} on {trade_date}."
            )

        ranked = sorted(
            candidates,
            key=lambda rule: (
                1 if rule.security_id is not None else 0,
                rule.effective_from,
                rule.version,
            ),
            reverse=True,
        )
        if len(ranked) > 1 and _same_resolution_rank(ranked[0], ranked[1]):
            raise RuleMissing(
                "Ambiguous market rule resolution for "
                f"{_enum_value(exchange)} {_enum_value(asset_type)} {security_id} on {trade_date}."
            )
        return ranked[0]


class MarketRuleEngine:
    """Applies resolved market rules to order and data visibility checks."""

    def __init__(self, repository: InMemoryRuleRepository) -> None:
        self._repository = repository

    def resolve(self, security: SecurityRef, trade_date: date) -> SecurityRule:
        return self._repository.resolve(
            exchange=security.exchange,
            asset_type=security.asset_type,
            security_id=security.security_id,
            trade_date=trade_date,
        )

    def price_limit_band(self, rule: SecurityRule, previous_close: float) -> PriceLimitBand:
        tick_size = _required_decimal(rule, "tick_size", value=rule.tick_size)
        up_pct = _required_decimal(rule, "limit_up_pct", fallback_name="price_limit_pct")
        down_pct = _required_decimal(rule, "limit_down_pct", fallback_name="price_limit_pct")
        previous = Decimal(str(previous_close))
        upper = _round_to_tick(previous * (Decimal("1") + up_pct), tick_size, ROUND_FLOOR)
        lower = _round_to_tick(previous * (Decimal("1") - down_pct), tick_size, ROUND_CEILING)
        return PriceLimitBand(lower_price=float(lower), upper_price=float(upper))

    def sellable_quantity(
        self,
        rule: SecurityRule,
        *,
        total_position: int,
        bought_today: int,
    ) -> int:
        if rule.intraday_round_trip is None:
            raise RuleMissing(f"Rule {rule.rule_id} lacks intraday_round_trip.")
        if rule.intraday_round_trip:
            return max(total_position, 0)
        return max(total_position - bought_today, 0)

    def validate_order(
        self,
        rule: SecurityRule,
        *,
        side: OrderSide,
        trade_date: date,
        quantity: int,
        price: float,
        previous_close: float,
        total_position: int = 0,
        bought_today: int = 0,
        has_opposite_liquidity: bool = True,
    ) -> RuleValidationResult:
        reasons: list[str] = []
        if self.is_suspended(rule, trade_date):
            reasons.append("Security is suspended on trade_date.")

        lot_size = _required_int(rule, "lot_size", value=rule.lot_size)
        if quantity <= 0:
            reasons.append("Order quantity must be positive.")
        elif quantity % lot_size != 0:
            reasons.append(f"Order quantity must be a multiple of lot_size {lot_size}.")

        tick_size = _required_decimal(rule, "tick_size", value=rule.tick_size)
        if not _is_multiple_of_tick(Decimal(str(price)), tick_size):
            reasons.append(f"Order price must align to tick_size {tick_size}.")

        band = self.price_limit_band(rule, previous_close)
        if price > band.upper_price or price < band.lower_price:
            reasons.append("Order price is outside the effective price limit band.")

        if side is OrderSide.SELL:
            sellable = self.sellable_quantity(
                rule,
                total_position=total_position,
                bought_today=bought_today,
            )
            if quantity > sellable:
                reasons.append("Sell quantity exceeds currently sellable quantity.")

        if not has_opposite_liquidity:
            if side is OrderSide.BUY and price >= band.upper_price:
                reasons.append("Limit-up touch without sell-side liquidity is not executable.")
            if side is OrderSide.SELL and price <= band.lower_price:
                reasons.append("Limit-down touch without buy-side liquidity is not executable.")

        return RuleValidationResult(allowed=not reasons, reasons=tuple(reasons))

    def calculate_fees(
        self,
        rule: SecurityRule,
        *,
        side: OrderSide,
        notional: float,
    ) -> FeeBreakdown:
        commission_rate = _required_decimal(rule, "commission_rate")
        min_commission = _required_decimal(rule, "min_commission")
        transfer_fee_rate = _required_decimal(rule, "transfer_fee_rate")
        stamp_tax_rate = _required_decimal(rule, "stamp_tax_rate")
        notional_value = Decimal(str(notional))
        commission = max(notional_value * commission_rate, min_commission)
        transfer_fee = notional_value * transfer_fee_rate
        stamp_tax = notional_value * stamp_tax_rate if side is OrderSide.SELL else Decimal("0")
        total = commission + transfer_fee + stamp_tax
        return FeeBreakdown(
            commission=float(commission),
            stamp_tax=float(stamp_tax),
            transfer_fee=float(transfer_fee),
            total=float(total),
        )

    def is_suspended(self, rule: SecurityRule, trade_date: date) -> bool:
        if _extra(rule, "trading_enabled", default=True) is False:
            return True
        suspension_dates = _extra(rule, "suspension_dates", default=())
        return _date_in_values(trade_date, suspension_dates)

    def ensure_off_exchange_fund_uses_official_nav(
        self,
        rule: SecurityRule,
        nav: FundNav | EstimatedFundNav,
    ) -> None:
        if _enum_value(rule.asset_type) != AssetType.MUTUAL_FUND.value:
            raise DataInvalid("Official NAV semantic check requires a MUTUAL_FUND rule.")
        if isinstance(nav, EstimatedFundNav):
            raise DataInvalid("Estimated fund NAV cannot be used as official execution NAV.")

    def is_information_observable(self, *, available_at: datetime, as_of: datetime) -> bool:
        return available_at <= as_of


def _matches_rule(rule: SecurityRule, request: RuleResolutionRequest) -> bool:
    if rule.review_status is not RuleReviewStatus.APPROVED:
        return False
    if _enum_value(rule.exchange) != _enum_value(request.exchange):
        return False
    if _enum_value(rule.asset_type) != _enum_value(request.asset_type):
        return False
    if rule.security_id is not None and rule.security_id != request.security_id:
        return False
    if rule.effective_from > request.trade_date:
        return False
    if rule.effective_to is not None and rule.effective_to < request.trade_date:
        return False
    return True


def _same_resolution_rank(left: SecurityRule, right: SecurityRule) -> bool:
    return (
        (left.security_id is not None) == (right.security_id is not None)
        and left.effective_from == right.effective_from
        and left.version == right.version
    )


def _enum_value(value: Any) -> str:
    return value.value if isinstance(value, StrEnum) else str(value)


def _extra(rule: SecurityRule, name: str, *, default: Any = None) -> Any:
    extra = rule.model_extra or {}
    return extra.get(name, default)


def _required_int(rule: SecurityRule, name: str, *, value: int | None = None) -> int:
    resolved = value if value is not None else _extra(rule, name)
    if resolved is None:
        raise RuleMissing(f"Rule {rule.rule_id} lacks required integer field {name}.")
    return int(resolved)


def _required_decimal(
    rule: SecurityRule,
    name: str,
    *,
    value: float | int | None = None,
    fallback_name: str | None = None,
) -> Decimal:
    resolved = value if value is not None else _extra(rule, name)
    if resolved is None and fallback_name is not None:
        resolved = _extra(rule, fallback_name)
    if resolved is None:
        raise RuleMissing(f"Rule {rule.rule_id} lacks required numeric field {name}.")
    return Decimal(str(resolved))


def _round_to_tick(value: Decimal, tick_size: Decimal, rounding: str) -> Decimal:
    units = (value / tick_size).to_integral_value(rounding=rounding)
    return units * tick_size


def _is_multiple_of_tick(value: Decimal, tick_size: Decimal) -> bool:
    units = value / tick_size
    return units == units.to_integral_value()


def _date_in_values(day: date, values: Any) -> bool:
    if values is None:
        return False
    if isinstance(values, str):
        return day.isoformat() == values
    if isinstance(values, date):
        return day == values
    try:
        return any(_date_in_values(day, value) for value in values)
    except TypeError:
        return False


__all__ = [
    "FeeBreakdown",
    "InMemoryRuleRepository",
    "MarketRuleEngine",
    "OrderSide",
    "PriceLimitBand",
    "RuleResolutionRequest",
    "RuleValidationResult",
]
