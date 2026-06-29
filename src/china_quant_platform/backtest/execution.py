"""Execution cost, liquidity, latency, and corporate action models."""

from __future__ import annotations

from datetime import datetime, timedelta
from math import floor
from typing import Self

from pydantic import Field, model_validator

from china_quant_platform.domain import CorporateAction, CorporateActionType, SecurityRule
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import NonEmptyString
from china_quant_platform.rules import MarketRuleEngine, OrderSide


class ExecutionCostBreakdown(DomainModel):
    commission: float = Field(default=0, ge=0)
    stamp_tax: float = Field(default=0, ge=0)
    transfer_fee: float = Field(default=0, ge=0)
    slippage_cost: float = Field(default=0, ge=0)
    spread_cost: float = Field(default=0, ge=0)
    total: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def total_must_cover_components(self) -> Self:
        minimum_total = (
            self.commission
            + self.stamp_tax
            + self.transfer_fee
            + self.slippage_cost
            + self.spread_cost
        )
        if self.total + 1e-9 < minimum_total:
            raise ValueError("total must be at least the sum of execution cost components")
        return self


class RuleBasedCostModel:
    """Commission and tax model backed by the effective market rule."""

    def calculate(
        self,
        *,
        rule_engine: MarketRuleEngine,
        rule: SecurityRule,
        side: OrderSide,
        notional: float,
        slippage_cost: float = 0.0,
        spread_cost: float = 0.0,
    ) -> ExecutionCostBreakdown:
        fees = rule_engine.calculate_fees(rule, side=side, notional=notional)
        return ExecutionCostBreakdown(
            commission=fees.commission,
            stamp_tax=fees.stamp_tax,
            transfer_fee=fees.transfer_fee,
            slippage_cost=slippage_cost,
            spread_cost=spread_cost,
            total=fees.total + slippage_cost + spread_cost,
        )


class FixedBpsSlippageModel(DomainModel):
    bps: float = Field(default=0, ge=0)

    def adjust_price(self, *, side: OrderSide, price: float) -> float:
        adjustment = price * self.bps / 10_000.0
        if side in {OrderSide.BUY, OrderSide.SUBSCRIBE}:
            return price + adjustment
        return max(price - adjustment, 0.0)


class FixedSpreadModel(DomainModel):
    spread: float = Field(default=0, ge=0)

    def adjust_price(self, *, side: OrderSide, price: float) -> float:
        half_spread = self.spread / 2.0
        if side in {OrderSide.BUY, OrderSide.SUBSCRIBE}:
            return price + half_spread
        return max(price - half_spread, 0.0)


class ParticipationRateLiquidityModel(DomainModel):
    max_participation_rate: float = Field(gt=0, le=1)

    def max_fill_quantity(self, *, bar_volume: float, requested_quantity: int) -> int:
        if bar_volume <= 0:
            return 0
        return max(min(requested_quantity, floor(bar_volume * self.max_participation_rate)), 0)


class FixedLatencyModel(DomainModel):
    delay_seconds: float = Field(default=0, ge=0)

    def apply(self, timestamp: datetime) -> datetime:
        return timestamp + timedelta(seconds=self.delay_seconds)


class PositionState(DomainModel):
    security_id: NonEmptyString
    quantity: int = Field(ge=0)
    cash: float
    average_cost: float = Field(ge=0)


class CorporateActionImpact(DomainModel):
    security_id: NonEmptyString
    action_type: CorporateActionType
    cash_delta: float = 0.0
    share_delta: int = 0
    resulting_quantity: int = Field(ge=0)
    resulting_average_cost: float = Field(ge=0)


class CorporateActionProcessor:
    """Applies cash dividends and splits to position state at the event date."""

    def apply(
        self,
        *,
        position: PositionState,
        action: CorporateAction,
    ) -> tuple[PositionState, CorporateActionImpact]:
        if action.security_id != position.security_id:
            raise ValueError("corporate action security_id must match the position")

        if action.action_type is CorporateActionType.DIVIDEND:
            cash_delta = position.quantity * (action.cash_amount or 0.0)
            updated = position.model_copy(update={"cash": position.cash + cash_delta})
            return updated, CorporateActionImpact(
                security_id=position.security_id,
                action_type=action.action_type,
                cash_delta=cash_delta,
                share_delta=0,
                resulting_quantity=updated.quantity,
                resulting_average_cost=updated.average_cost,
            )

        if action.action_type is CorporateActionType.SPLIT:
            if action.share_ratio is None or action.share_ratio <= 0:
                raise ValueError("split corporate actions require positive share_ratio")
            new_quantity = floor(position.quantity * action.share_ratio)
            share_delta = new_quantity - position.quantity
            new_average_cost = (
                0.0
                if new_quantity == 0
                else position.average_cost * position.quantity / new_quantity
            )
            updated = position.model_copy(
                update={"quantity": new_quantity, "average_cost": new_average_cost}
            )
            return updated, CorporateActionImpact(
                security_id=position.security_id,
                action_type=action.action_type,
                cash_delta=0.0,
                share_delta=share_delta,
                resulting_quantity=updated.quantity,
                resulting_average_cost=updated.average_cost,
            )

        return position, CorporateActionImpact(
            security_id=position.security_id,
            action_type=action.action_type,
            cash_delta=0.0,
            share_delta=0,
            resulting_quantity=position.quantity,
            resulting_average_cost=position.average_cost,
        )
