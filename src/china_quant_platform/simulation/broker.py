"""Stateful paper-trading broker with no real order submission path."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field

from china_quant_platform.backtest import (
    DeterministicExecutionSimulator,
    ExecutionReport,
    ExecutionStatus,
    OrderIntent,
)
from china_quant_platform.domain import DataHealth, Quote, SecurityRef
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import NonEmptyString
from china_quant_platform.portfolio import (
    PortfolioEngine,
    PortfolioReconciliation,
    PortfolioState,
)
from china_quant_platform.rules import MarketRuleEngine

REAL_ORDER_SUBMISSION_ENABLED = False


class SimulationOrderStatus(StrEnum):
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    REJECTED = "REJECTED"


class SimulationBrokerConfig(DomainModel):
    account_id: NonEmptyString
    reject_blocked_data: bool = True
    deviation_alert_threshold: float = Field(default=0.01, ge=0)


class SimulationAccountMetrics(DomainModel):
    cash: float
    market_value: float
    net_asset_value: float
    realized_pnl: float
    unrealized_pnl: float


class SignalExecutionDeviation(DomainModel):
    source_signal_id: NonEmptyString
    order_id: NonEmptyString
    expected_price: float = Field(gt=0)
    fill_price: float | None = Field(default=None, gt=0)
    slippage_pct: float | None = None
    filled_ratio: float = Field(ge=0, le=1)
    threshold_breached: bool = False
    reasons: tuple[NonEmptyString, ...] = ()


class SimulationOrderRecord(DomainModel):
    order: OrderIntent
    status: SimulationOrderStatus
    submitted_at: AwareDatetime
    reasons: tuple[NonEmptyString, ...] = ()


class SimulationExecutionRecord(DomainModel):
    order_id: NonEmptyString
    report: ExecutionReport
    executed_at: AwareDatetime
    expected_price: float = Field(gt=0)
    actual_price: float | None = Field(default=None, gt=0)
    filled_ratio: float = Field(ge=0, le=1)
    cash_after: float
    net_asset_value_after: float


class SimulationAccountState(DomainModel):
    account_id: NonEmptyString
    portfolio: PortfolioState
    orders: tuple[SimulationOrderRecord, ...] = ()
    executions: tuple[SimulationExecutionRecord, ...] = ()
    deviations: tuple[SignalExecutionDeviation, ...] = ()
    updated_at: AwareDatetime | None = None

    @property
    def metrics(self) -> SimulationAccountMetrics:
        realized = sum(position.realized_pnl for position in self.portfolio.positions.values())
        unrealized = sum(
            (position.last_price - position.average_cost) * position.quantity
            for position in self.portfolio.positions.values()
        )
        return SimulationAccountMetrics(
            cash=self.portfolio.cash,
            market_value=self.portfolio.market_value,
            net_asset_value=self.portfolio.net_asset_value,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
        )


class SimulationOrderResult(DomainModel):
    state: SimulationAccountState
    order_record: SimulationOrderRecord
    execution_record: SimulationExecutionRecord
    deviation: SignalExecutionDeviation
    reconciliation: PortfolioReconciliation


class SimulationBroker:
    """Paper broker that can only simulate orders against local rules and quotes."""

    def __init__(
        self,
        *,
        config: SimulationBrokerConfig,
        rule_engine: MarketRuleEngine,
        initial_cash: float,
        state: SimulationAccountState | None = None,
        execution_simulator: DeterministicExecutionSimulator | None = None,
        portfolio_engine: PortfolioEngine | None = None,
    ) -> None:
        if initial_cash <= 0 and state is None:
            raise ValueError("initial_cash must be positive when state is not provided")
        self._config = config
        self._rule_engine = rule_engine
        self._execution_simulator = execution_simulator or DeterministicExecutionSimulator()
        self._portfolio_engine = portfolio_engine or PortfolioEngine()
        self._state = state or SimulationAccountState(
            account_id=config.account_id,
            portfolio=PortfolioState(cash=initial_cash),
        )
        if self._state.account_id != config.account_id:
            raise ValueError("state account_id must match broker config account_id")

    @property
    def state(self) -> SimulationAccountState:
        return self._state

    def submit_order(
        self,
        *,
        order: OrderIntent,
        security: SecurityRef,
        quote: Quote,
        data_health: DataHealth,
    ) -> SimulationOrderResult:
        _validate_order_inputs(order=order, security=security, quote=quote)
        report = (
            _blocked_data_report(order, data_health)
            if self._config.reject_blocked_data and data_health.block_signal
            else self._simulate(order=order, security=security, quote=quote)
        )
        portfolio = self._portfolio_engine.apply_execution(
            portfolio=self._state.portfolio,
            order=order,
            report=report,
        )
        status = _simulation_status(report.status)
        order_record = SimulationOrderRecord(
            order=order,
            status=status,
            submitted_at=order.created_at,
            reasons=report.reasons,
        )
        execution_record = SimulationExecutionRecord(
            order_id=order.order_id,
            report=report,
            executed_at=order.created_at,
            expected_price=order.price,
            actual_price=report.fill_price,
            filled_ratio=_filled_ratio(report, order),
            cash_after=portfolio.cash,
            net_asset_value_after=portfolio.net_asset_value,
        )
        deviation = _deviation(
            order=order,
            report=report,
            threshold=self._config.deviation_alert_threshold,
        )
        self._state = self._state.model_copy(
            update={
                "portfolio": portfolio,
                "orders": (*self._state.orders, order_record),
                "executions": (*self._state.executions, execution_record),
                "deviations": (*self._state.deviations, deviation),
                "updated_at": quote.received_at,
            }
        )
        return SimulationOrderResult(
            state=self._state,
            order_record=order_record,
            execution_record=execution_record,
            deviation=deviation,
            reconciliation=self._state.portfolio.reconcile(),
        )

    def mark_to_market(
        self,
        *,
        prices: dict[str, float],
        updated_at: AwareDatetime,
    ) -> SimulationAccountState:
        self._state = self._state.model_copy(
            update={
                "portfolio": self._state.portfolio.mark_to_market(prices),
                "updated_at": updated_at,
            }
        )
        return self._state

    def export_state(self) -> str:
        return export_simulation_state(self._state)

    @classmethod
    def from_snapshot(
        cls,
        *,
        payload: str,
        config: SimulationBrokerConfig,
        rule_engine: MarketRuleEngine,
        initial_cash: float,
        execution_simulator: DeterministicExecutionSimulator | None = None,
        portfolio_engine: PortfolioEngine | None = None,
    ) -> Self:
        return cls(
            config=config,
            rule_engine=rule_engine,
            initial_cash=initial_cash,
            state=restore_simulation_state(payload),
            execution_simulator=execution_simulator,
            portfolio_engine=portfolio_engine,
        )

    def _simulate(
        self,
        *,
        order: OrderIntent,
        security: SecurityRef,
        quote: Quote,
    ) -> ExecutionReport:
        position = self._state.portfolio.positions.get(order.security_id)
        total_position = 0 if position is None else position.quantity
        sellable_quantity = 0 if position is None else position.sellable_quantity
        bought_today = max(total_position - sellable_quantity, 0)
        return self._execution_simulator.simulate(
            order=order,
            security=security,
            rule_engine=self._rule_engine,
            previous_close=quote.previous_close,
            total_position=total_position,
            bought_today=bought_today,
        )


def export_simulation_state(state: SimulationAccountState) -> str:
    return json.dumps(
        state.to_contract_dict(),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def restore_simulation_state(payload: str) -> SimulationAccountState:
    return SimulationAccountState.from_contract_dict(json.loads(payload))


def simulation_state_checksum(state: SimulationAccountState) -> str:
    return hashlib.sha256(export_simulation_state(state).encode("utf-8")).hexdigest()


def _validate_order_inputs(
    *,
    order: OrderIntent,
    security: SecurityRef,
    quote: Quote,
) -> None:
    if order.security_id != security.security_id:
        raise ValueError("order security_id must match security")
    if quote.security_id != security.security_id:
        raise ValueError("quote security_id must match security")


def _blocked_data_report(order: OrderIntent, data_health: DataHealth) -> ExecutionReport:
    issue_text = "; ".join(data_health.issues) or data_health.status.value
    return ExecutionReport(
        order_id=order.order_id,
        status=ExecutionStatus.REJECTED,
        filled_quantity=0,
        reasons=(f"Simulation blocked by data health: {issue_text}",),
    )


def _simulation_status(status: ExecutionStatus) -> SimulationOrderStatus:
    if status is ExecutionStatus.FILLED:
        return SimulationOrderStatus.FILLED
    if status is ExecutionStatus.PARTIALLY_FILLED:
        return SimulationOrderStatus.PARTIALLY_FILLED
    return SimulationOrderStatus.REJECTED


def _filled_ratio(report: ExecutionReport, order: OrderIntent) -> float:
    return report.filled_quantity / order.quantity


def _deviation(
    *,
    order: OrderIntent,
    report: ExecutionReport,
    threshold: float,
) -> SignalExecutionDeviation:
    filled_ratio = _filled_ratio(report, order)
    if report.fill_price is None:
        return SignalExecutionDeviation(
            source_signal_id=order.source_signal_id,
            order_id=order.order_id,
            expected_price=order.price,
            fill_price=None,
            slippage_pct=None,
            filled_ratio=filled_ratio,
            threshold_breached=False,
            reasons=report.reasons,
        )
    slippage_pct = report.fill_price / order.price - 1.0
    return SignalExecutionDeviation(
        source_signal_id=order.source_signal_id,
        order_id=order.order_id,
        expected_price=order.price,
        fill_price=report.fill_price,
        slippage_pct=slippage_pct,
        filled_ratio=filled_ratio,
        threshold_breached=abs(slippage_pct) > threshold or filled_ratio < 1.0,
        reasons=report.reasons,
    )
