"""Portfolio accounting, position state, and reconciliation helpers."""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from china_quant_platform.backtest import ExecutionReport, ExecutionStatus, OrderIntent
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import NonEmptyString
from china_quant_platform.rules import OrderSide


class Position(DomainModel):
    security_id: NonEmptyString
    quantity: int = Field(ge=0)
    sellable_quantity: int = Field(ge=0)
    average_cost: float = Field(ge=0)
    last_price: float = Field(ge=0)
    realized_pnl: float = 0.0

    @model_validator(mode="after")
    def sellable_cannot_exceed_quantity(self) -> Self:
        if self.sellable_quantity > self.quantity:
            raise ValueError("sellable_quantity cannot exceed quantity")
        return self

    @property
    def market_value(self) -> float:
        return self.quantity * self.last_price


class PortfolioReconciliation(DomainModel):
    cash: float
    market_value: float
    net_asset_value: float
    expected_net_asset_value: float
    difference: float
    balanced: bool


class PortfolioState(DomainModel):
    cash: float
    positions: dict[str, Position] = Field(default_factory=dict)

    @property
    def market_value(self) -> float:
        return sum(position.market_value for position in self.positions.values())

    @property
    def net_asset_value(self) -> float:
        return self.cash + self.market_value

    def position_weight(self, security_id: str) -> float:
        if self.net_asset_value <= 0:
            return 0.0
        position = self.positions.get(security_id)
        return 0.0 if position is None else position.market_value / self.net_asset_value

    def weights(self) -> dict[str, float]:
        return {
            security_id: self.position_weight(security_id) for security_id in sorted(self.positions)
        }

    def mark_to_market(self, prices: dict[str, float]) -> PortfolioState:
        positions = dict(self.positions)
        for security_id, price in prices.items():
            if security_id in positions:
                positions[security_id] = positions[security_id].model_copy(
                    update={"last_price": price}
                )
        return self.model_copy(update={"positions": positions})

    def reconcile(
        self,
        *,
        expected_net_asset_value: float | None = None,
        tolerance: float = 1e-9,
    ) -> PortfolioReconciliation:
        expected = (
            self.net_asset_value if expected_net_asset_value is None else expected_net_asset_value
        )
        difference = self.net_asset_value - expected
        return PortfolioReconciliation(
            cash=self.cash,
            market_value=self.market_value,
            net_asset_value=self.net_asset_value,
            expected_net_asset_value=expected,
            difference=difference,
            balanced=abs(difference) <= tolerance,
        )


class PortfolioEngine:
    def apply_execution(
        self,
        *,
        portfolio: PortfolioState,
        order: OrderIntent,
        report: ExecutionReport,
    ) -> PortfolioState:
        if report.status is ExecutionStatus.REJECTED or report.filled_quantity == 0:
            return portfolio
        if report.fill_price is None:
            raise ValueError("filled execution reports must include fill_price")
        position = portfolio.positions.get(
            order.security_id,
            Position(
                security_id=order.security_id,
                quantity=0,
                sellable_quantity=0,
                average_cost=0.0,
                last_price=report.fill_price,
            ),
        )

        if order.side in {OrderSide.BUY, OrderSide.SUBSCRIBE}:
            return _apply_buy(portfolio, position, order, report)
        return _apply_sell(portfolio, position, order, report)


def _apply_buy(
    portfolio: PortfolioState,
    position: Position,
    order: OrderIntent,
    report: ExecutionReport,
) -> PortfolioState:
    assert report.fill_price is not None
    fill_notional = report.fill_price * report.filled_quantity
    total_quantity = position.quantity + report.filled_quantity
    average_cost = (
        0.0
        if total_quantity == 0
        else (position.average_cost * position.quantity + fill_notional + report.costs.total)
        / total_quantity
    )
    updated_position = position.model_copy(
        update={
            "quantity": total_quantity,
            "average_cost": average_cost,
            "last_price": report.fill_price,
        }
    )
    positions = dict(portfolio.positions)
    positions[order.security_id] = updated_position
    return portfolio.model_copy(
        update={"cash": portfolio.cash - fill_notional - report.costs.total, "positions": positions}
    )


def _apply_sell(
    portfolio: PortfolioState,
    position: Position,
    order: OrderIntent,
    report: ExecutionReport,
) -> PortfolioState:
    assert report.fill_price is not None
    if report.filled_quantity > position.sellable_quantity:
        raise ValueError("sell filled_quantity exceeds sellable_quantity")
    fill_notional = report.fill_price * report.filled_quantity
    remaining_quantity = position.quantity - report.filled_quantity
    realized_pnl = (
        position.realized_pnl
        + (report.fill_price - position.average_cost) * report.filled_quantity
        - report.costs.total
    )
    updated_position = position.model_copy(
        update={
            "quantity": remaining_quantity,
            "sellable_quantity": min(
                position.sellable_quantity - report.filled_quantity, remaining_quantity
            ),
            "last_price": report.fill_price,
            "realized_pnl": realized_pnl,
            "average_cost": 0.0 if remaining_quantity == 0 else position.average_cost,
        }
    )
    positions = dict(portfolio.positions)
    if updated_position.quantity == 0:
        positions.pop(order.security_id, None)
    else:
        positions[order.security_id] = updated_position
    return portfolio.model_copy(
        update={"cash": portfolio.cash + fill_notional - report.costs.total, "positions": positions}
    )
