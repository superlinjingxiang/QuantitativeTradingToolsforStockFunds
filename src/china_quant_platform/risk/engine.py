"""Portfolio risk limits and position sizing."""

from __future__ import annotations

from math import floor

from pydantic import Field

from china_quant_platform.backtest import OrderIntent
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.portfolio import PortfolioState
from china_quant_platform.rules import OrderSide


class RiskLimitConfig(DomainModel):
    max_single_position_weight: float = Field(gt=0, le=1)
    max_total_exposure: float = Field(gt=0, le=1)
    max_drawdown: float = Field(ge=0, le=1)
    max_order_participation_rate: float = Field(gt=0, le=1)
    min_cash_buffer: float = Field(default=0, ge=0, le=1)
    max_pairwise_correlation: float = Field(default=1.0, ge=-1, le=1)


class RiskCheckResult(DomainModel):
    allowed: bool
    reasons: tuple[str, ...] = ()
    projected_weight: float = 0.0
    projected_total_exposure: float = 0.0
    target_position_limit: float | None = Field(default=None, ge=0, le=1)


class RiskEngine:
    def __init__(self, config: RiskLimitConfig) -> None:
        self._config = config

    def evaluate_order(
        self,
        *,
        portfolio: PortfolioState,
        order: OrderIntent,
        latest_prices: dict[str, float],
        average_daily_volume: dict[str, float],
        peak_net_asset_value: float | None = None,
        correlations: dict[tuple[str, str], float] | None = None,
    ) -> RiskCheckResult:
        price = latest_prices.get(order.security_id, order.price)
        projected_positions = {
            security_id: position.quantity for security_id, position in portfolio.positions.items()
        }
        current_quantity = projected_positions.get(order.security_id, 0)
        if order.side in {OrderSide.BUY, OrderSide.SUBSCRIBE}:
            projected_positions[order.security_id] = current_quantity + order.quantity
        else:
            projected_positions[order.security_id] = max(current_quantity - order.quantity, 0)

        nav = portfolio.net_asset_value
        projected_values = {
            security_id: quantity * latest_prices.get(security_id, price)
            for security_id, quantity in projected_positions.items()
        }
        projected_market_value = sum(projected_values.values())
        projected_weight = 0.0 if nav <= 0 else projected_values.get(order.security_id, 0.0) / nav
        projected_total_exposure = 0.0 if nav <= 0 else projected_market_value / nav
        reasons: list[str] = []

        if projected_weight > self._config.max_single_position_weight:
            reasons.append("Single position weight exceeds limit.")
        if projected_total_exposure > self._config.max_total_exposure:
            reasons.append("Total exposure exceeds limit.")

        if order.side in {OrderSide.BUY, OrderSide.SUBSCRIBE}:
            projected_cash = portfolio.cash - order.quantity * price
            if nav > 0 and projected_cash < nav * self._config.min_cash_buffer:
                reasons.append("Cash buffer would fall below limit.")

        average_volume = average_daily_volume.get(order.security_id)
        if average_volume is not None and average_volume > 0:
            if order.quantity > average_volume * self._config.max_order_participation_rate:
                reasons.append("Order quantity exceeds liquidity participation limit.")

        if peak_net_asset_value is not None and peak_net_asset_value > 0:
            drawdown = max(0.0, 1.0 - nav / peak_net_asset_value)
            if drawdown > self._config.max_drawdown:
                reasons.append("Portfolio drawdown exceeds limit.")

        if correlations is not None and order.side in {OrderSide.BUY, OrderSide.SUBSCRIBE}:
            for security_id, quantity in projected_positions.items():
                if security_id == order.security_id or quantity <= 0:
                    continue
                correlation = _lookup_correlation(correlations, order.security_id, security_id)
                if correlation is not None and correlation > self._config.max_pairwise_correlation:
                    reasons.append("Pairwise correlation exceeds limit.")
                    break

        return RiskCheckResult(
            allowed=not reasons,
            reasons=tuple(reasons),
            projected_weight=projected_weight,
            projected_total_exposure=projected_total_exposure,
            target_position_limit=self._config.max_single_position_weight,
        )


def position_size_by_risk_budget(
    *,
    net_asset_value: float,
    entry_price: float,
    stop_price: float,
    risk_budget_pct: float,
    lot_size: int = 1,
) -> int:
    if net_asset_value <= 0:
        return 0
    if entry_price <= stop_price:
        raise ValueError("entry_price must be greater than stop_price for long risk sizing")
    if risk_budget_pct <= 0:
        return 0
    if lot_size < 1:
        raise ValueError("lot_size must be at least 1")

    risk_amount = net_asset_value * risk_budget_pct
    raw_quantity = floor(risk_amount / (entry_price - stop_price))
    return raw_quantity - raw_quantity % lot_size


def _lookup_correlation(
    correlations: dict[tuple[str, str], float],
    left: str,
    right: str,
) -> float | None:
    return correlations.get((left, right), correlations.get((right, left)))
