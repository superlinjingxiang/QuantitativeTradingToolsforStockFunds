"""Deterministic event-driven backtest kernel."""

from __future__ import annotations

import hashlib
import heapq
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from china_quant_platform.backtest.execution import (
    ExecutionCostBreakdown,
    FixedBpsSlippageModel,
    FixedLatencyModel,
    FixedSpreadModel,
    ParticipationRateLiquidityModel,
    RuleBasedCostModel,
)
from china_quant_platform.domain import BacktestConfig, Bar, SecurityRef
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.errors import InsufficientHistory
from china_quant_platform.domain.identifiers import NonEmptyString
from china_quant_platform.rules import MarketRuleEngine, OrderSide
from china_quant_platform.strategies import (
    RawSignal,
    RawSignalIntent,
    Strategy,
    StrategyContext,
    evaluate_strategy,
)

type StrategyContextFactory = Callable[[Bar, int], StrategyContext]
type OrderPolicy = Callable[[RawSignal, StrategyContext, Bar, BacktestClock], OrderIntent | None]
type BacktestEventCallback = Callable[[BacktestEvent, BacktestCancellationToken], None]


class BacktestEventType(StrEnum):
    MARKET = "MARKET"
    STRATEGY_EVALUATION = "STRATEGY_EVALUATION"
    SIGNAL = "SIGNAL"
    ORDER = "ORDER"
    FILL = "FILL"
    PARTIAL_FILL = "PARTIAL_FILL"
    REJECT = "REJECT"
    AUDIT = "AUDIT"
    CANCELLED = "CANCELLED"


class ExecutionStatus(StrEnum):
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    REJECTED = "REJECTED"


EVENT_PRIORITIES: dict[BacktestEventType, int] = {
    BacktestEventType.MARKET: 10,
    BacktestEventType.STRATEGY_EVALUATION: 20,
    BacktestEventType.SIGNAL: 30,
    BacktestEventType.ORDER: 40,
    BacktestEventType.FILL: 50,
    BacktestEventType.PARTIAL_FILL: 50,
    BacktestEventType.REJECT: 50,
    BacktestEventType.AUDIT: 90,
    BacktestEventType.CANCELLED: 99,
}


class TradingSession(DomainModel):
    open_time: time
    close_time: time

    @model_validator(mode="after")
    def open_must_precede_close(self) -> Self:
        if self.open_time >= self.close_time:
            raise ValueError("open_time must be earlier than close_time")
        return self


class BacktestClock:
    """Trading-session helper using the timezone carried by input datetimes."""

    def __init__(
        self,
        sessions: Sequence[TradingSession] = (
            TradingSession(open_time=time(9, 30), close_time=time(11, 30)),
            TradingSession(open_time=time(13, 0), close_time=time(15, 0)),
        ),
    ) -> None:
        self._sessions = tuple(sorted(sessions, key=lambda session: session.open_time))

    def is_session_time(self, moment: datetime) -> bool:
        if moment.weekday() >= 5:
            return False
        current_time = moment.timetz().replace(tzinfo=None)
        return any(
            session.open_time <= current_time <= session.close_time for session in self._sessions
        )

    def next_session_open(self, moment: datetime) -> datetime:
        candidate_date = moment.date()
        while True:
            if candidate_date.weekday() < 5:
                for session in self._sessions:
                    candidate = datetime.combine(
                        candidate_date,
                        session.open_time,
                        tzinfo=moment.tzinfo,
                    )
                    if candidate > moment:
                        return candidate
            candidate_date += timedelta(days=1)


class OrderIntent(DomainModel):
    order_id: NonEmptyString
    security_id: NonEmptyString
    side: OrderSide
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    created_at: AwareDatetime
    trade_date: date
    source_signal_id: NonEmptyString
    strategy_id: NonEmptyString

    @model_validator(mode="after")
    def trade_date_must_match_created_at(self) -> Self:
        if self.trade_date != self.created_at.date():
            raise ValueError("trade_date must match created_at date")
        return self


class ExecutionReport(DomainModel):
    order_id: NonEmptyString
    status: ExecutionStatus
    filled_quantity: int = Field(ge=0)
    fill_price: float | None = Field(default=None, gt=0)
    notional: float = Field(default=0, ge=0)
    costs: ExecutionCostBreakdown = Field(default_factory=ExecutionCostBreakdown)
    reasons: tuple[NonEmptyString, ...] = ()

    @model_validator(mode="after")
    def filled_status_must_have_price(self) -> Self:
        if self.status in {ExecutionStatus.FILLED, ExecutionStatus.PARTIALLY_FILLED}:
            if self.filled_quantity <= 0:
                raise ValueError("filled executions must have positive filled_quantity")
            if self.fill_price is None:
                raise ValueError("filled executions must include fill_price")
        if self.status is ExecutionStatus.REJECTED and not self.reasons:
            raise ValueError("rejected executions must include reasons")
        return self


class BacktestEvent(DomainModel):
    sequence: int = Field(ge=1)
    event_id: NonEmptyString
    event_type: BacktestEventType
    timestamp: AwareDatetime
    security_id: NonEmptyString | None = None
    strategy_id: NonEmptyString | None = None
    order_id: NonEmptyString | None = None
    bar_index: int | None = Field(default=None, ge=0)
    signal_intent: RawSignalIntent | None = None
    execution_status: ExecutionStatus | None = None
    quantity: int | None = Field(default=None, ge=0)
    filled_quantity: int | None = Field(default=None, ge=0)
    price: float | None = Field(default=None, ge=0)
    notional: float | None = Field(default=None, ge=0)
    total_fees: float | None = Field(default=None, ge=0)
    slippage_cost: float | None = Field(default=None, ge=0)
    spread_cost: float | None = Field(default=None, ge=0)
    message: str | None = None
    reasons: tuple[NonEmptyString, ...] = ()


class BacktestRunResult(DomainModel):
    events: tuple[BacktestEvent, ...]
    cancelled: bool
    checksum: NonEmptyString


class BacktestCancellationToken:
    def __init__(self) -> None:
        self._cancelled = False

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True


@dataclass(order=True, slots=True)
class _ScheduledBacktestEvent:
    timestamp: datetime
    priority: int
    sequence: int
    event: BacktestEvent = field(compare=False)


class BacktestEventLoop:
    def __init__(self) -> None:
        self._pending: list[_ScheduledBacktestEvent] = []

    def schedule(self, event: BacktestEvent) -> None:
        heapq.heappush(
            self._pending,
            _ScheduledBacktestEvent(
                timestamp=event.timestamp,
                priority=EVENT_PRIORITIES[event.event_type],
                sequence=event.sequence,
                event=event,
            ),
        )

    def pop_next(self) -> BacktestEvent | None:
        if not self._pending:
            return None
        return heapq.heappop(self._pending).event

    @property
    def has_pending(self) -> bool:
        return bool(self._pending)


class DeterministicExecutionSimulator:
    def __init__(
        self,
        *,
        max_fill_quantity_per_order: int | None = None,
        has_opposite_liquidity: bool = True,
        cost_model: RuleBasedCostModel | None = None,
        slippage_model: FixedBpsSlippageModel | None = None,
        spread_model: FixedSpreadModel | None = None,
        liquidity_model: ParticipationRateLiquidityModel | None = None,
        latency_model: FixedLatencyModel | None = None,
    ) -> None:
        if max_fill_quantity_per_order is not None and max_fill_quantity_per_order < 1:
            raise ValueError("max_fill_quantity_per_order must be positive when provided")
        self._max_fill_quantity_per_order = max_fill_quantity_per_order
        self._has_opposite_liquidity = has_opposite_liquidity
        self._cost_model = cost_model or RuleBasedCostModel()
        self._slippage_model = slippage_model or FixedBpsSlippageModel()
        self._spread_model = spread_model or FixedSpreadModel()
        self._liquidity_model = liquidity_model
        self._latency_model = latency_model or FixedLatencyModel()

    def apply_latency(self, order: OrderIntent) -> OrderIntent:
        delayed = self._latency_model.apply(order.created_at)
        if delayed == order.created_at:
            return order
        return order.model_copy(update={"created_at": delayed, "trade_date": delayed.date()})

    def simulate(
        self,
        *,
        order: OrderIntent,
        security: SecurityRef,
        rule_engine: MarketRuleEngine,
        previous_close: float,
        total_position: int,
        bought_today: int,
        bar: Bar | None = None,
    ) -> ExecutionReport:
        rule = rule_engine.resolve(security, order.trade_date)
        validation = rule_engine.validate_order(
            rule,
            side=order.side,
            trade_date=order.trade_date,
            quantity=order.quantity,
            price=order.price,
            previous_close=previous_close,
            total_position=total_position,
            bought_today=bought_today,
            has_opposite_liquidity=self._has_opposite_liquidity,
        )
        if not validation.allowed:
            return ExecutionReport(
                order_id=order.order_id,
                status=ExecutionStatus.REJECTED,
                filled_quantity=0,
                reasons=validation.reasons,
            )

        fill_quantity = order.quantity
        if self._max_fill_quantity_per_order is not None:
            fill_quantity = min(fill_quantity, self._max_fill_quantity_per_order)
        if self._liquidity_model is not None:
            if bar is None:
                fill_quantity = 0
            else:
                fill_quantity = min(
                    fill_quantity,
                    self._liquidity_model.max_fill_quantity(
                        bar_volume=bar.volume,
                        requested_quantity=order.quantity,
                    ),
                )
        if fill_quantity <= 0:
            return ExecutionReport(
                order_id=order.order_id,
                status=ExecutionStatus.REJECTED,
                filled_quantity=0,
                reasons=("Liquidity model produced zero fillable quantity.",),
            )

        status = (
            ExecutionStatus.PARTIALLY_FILLED
            if fill_quantity < order.quantity
            else ExecutionStatus.FILLED
        )
        spread_price = self._spread_model.adjust_price(side=order.side, price=order.price)
        fill_price = self._slippage_model.adjust_price(side=order.side, price=spread_price)
        spread_cost = abs(spread_price - order.price) * fill_quantity
        slippage_cost = abs(fill_price - spread_price) * fill_quantity
        notional = fill_price * fill_quantity
        costs = self._cost_model.calculate(
            rule_engine=rule_engine,
            rule=rule,
            side=order.side,
            notional=notional,
            slippage_cost=slippage_cost,
            spread_cost=spread_cost,
        )
        return ExecutionReport(
            order_id=order.order_id,
            status=status,
            filled_quantity=fill_quantity,
            fill_price=fill_price,
            notional=notional,
            costs=costs,
        )


class BacktestEngine:
    def __init__(
        self,
        *,
        rule_engine: MarketRuleEngine,
        clock: BacktestClock | None = None,
        execution_simulator: DeterministicExecutionSimulator | None = None,
    ) -> None:
        self._rule_engine = rule_engine
        self._clock = clock or BacktestClock()
        self._execution_simulator = execution_simulator or DeterministicExecutionSimulator()

    def run(
        self,
        *,
        config: BacktestConfig,
        security: SecurityRef,
        bars: Sequence[Bar],
        strategy: Strategy,
        order_policy: OrderPolicy,
        context_factory: StrategyContextFactory | None = None,
        cancellation_token: BacktestCancellationToken | None = None,
        on_event: BacktestEventCallback | None = None,
        initial_position: int = 0,
    ) -> BacktestRunResult:
        token = cancellation_token or BacktestCancellationToken()
        loop = BacktestEventLoop()
        events: list[BacktestEvent] = []
        bars_by_index = tuple(
            bar
            for bar in sorted(bars, key=lambda item: (item.observed_at, item.end_time))
            if config.start_date <= bar.trade_date <= config.end_date
        )
        sequence = 0
        total_position = initial_position
        bought_today = 0
        active_trade_date: date | None = None

        def next_sequence() -> int:
            nonlocal sequence
            sequence += 1
            return sequence

        def make_event(
            event_type: BacktestEventType,
            timestamp: datetime,
            **data: object,
        ) -> BacktestEvent:
            event_sequence = next_sequence()
            return BacktestEvent.model_validate(
                {
                    "sequence": event_sequence,
                    "event_id": f"event-{event_sequence:06d}",
                    "event_type": event_type,
                    "timestamp": timestamp,
                    **data,
                }
            )

        for index, bar in enumerate(bars_by_index):
            loop.schedule(
                make_event(
                    BacktestEventType.MARKET,
                    bar.observed_at,
                    security_id=bar.security_id,
                    bar_index=index,
                    price=bar.close_price,
                    message="market bar observed",
                )
            )

        def record(event: BacktestEvent) -> None:
            events.append(event)
            if on_event is not None:
                on_event(event, token)

        while loop.has_pending and not token.is_cancelled:
            event = loop.pop_next()
            if event is None:
                break
            record(event)
            if token.is_cancelled:
                break
            if event.event_type is not BacktestEventType.MARKET or event.bar_index is None:
                continue

            bar = bars_by_index[event.bar_index]
            available_bars = event.bar_index + 1
            context = (
                context_factory(bar, available_bars)
                if context_factory is not None
                else _default_strategy_context(config, security, bar, available_bars)
            )

            try:
                evaluation = evaluate_strategy(strategy, context)
            except InsufficientHistory as exc:
                loop.schedule(
                    make_event(
                        BacktestEventType.AUDIT,
                        bar.observed_at,
                        security_id=security.security_id,
                        strategy_id=strategy.strategy_id,
                        bar_index=event.bar_index,
                        message=str(exc),
                    )
                )
                continue

            loop.schedule(
                make_event(
                    BacktestEventType.STRATEGY_EVALUATION,
                    evaluation.signal.generated_at,
                    security_id=security.security_id,
                    strategy_id=strategy.strategy_id,
                    bar_index=event.bar_index,
                    message="strategy evaluated",
                )
            )
            loop.schedule(
                make_event(
                    BacktestEventType.SIGNAL,
                    evaluation.signal.generated_at,
                    security_id=security.security_id,
                    strategy_id=strategy.strategy_id,
                    bar_index=event.bar_index,
                    signal_intent=evaluation.signal.intent,
                    message=evaluation.explanation.summary,
                )
            )

            order = order_policy(evaluation.signal, context, bar, self._clock)
            if order is None:
                loop.schedule(
                    make_event(
                        BacktestEventType.AUDIT,
                        evaluation.signal.generated_at,
                        security_id=security.security_id,
                        strategy_id=strategy.strategy_id,
                        bar_index=event.bar_index,
                        message="signal produced no order intent",
                    )
                )
                continue
            order = self._execution_simulator.apply_latency(order)
            if order.created_at <= evaluation.signal.generated_at:
                raise ValueError("order.created_at must be later than signal.generated_at")

            loop.schedule(
                make_event(
                    BacktestEventType.ORDER,
                    order.created_at,
                    security_id=order.security_id,
                    strategy_id=order.strategy_id,
                    order_id=order.order_id,
                    bar_index=event.bar_index,
                    quantity=order.quantity,
                    price=order.price,
                    message="order intent accepted by backtest engine",
                )
            )

            if active_trade_date != order.trade_date:
                active_trade_date = order.trade_date
                bought_today = 0

            report = self._execution_simulator.simulate(
                order=order,
                security=security,
                rule_engine=self._rule_engine,
                previous_close=bar.close_price,
                total_position=total_position,
                bought_today=bought_today,
                bar=bar,
            )
            if report.status in {ExecutionStatus.FILLED, ExecutionStatus.PARTIALLY_FILLED}:
                if order.side is OrderSide.BUY:
                    total_position += report.filled_quantity
                    bought_today += report.filled_quantity
                elif order.side is OrderSide.SELL:
                    total_position -= report.filled_quantity

            execution_event_type = _event_type_for_execution(report.status)
            loop.schedule(
                make_event(
                    execution_event_type,
                    order.created_at,
                    security_id=order.security_id,
                    strategy_id=order.strategy_id,
                    order_id=order.order_id,
                    bar_index=event.bar_index,
                    execution_status=report.status,
                    quantity=order.quantity,
                    filled_quantity=report.filled_quantity,
                    price=report.fill_price or order.price,
                    notional=report.notional,
                    total_fees=report.costs.total,
                    slippage_cost=report.costs.slippage_cost,
                    spread_cost=report.costs.spread_cost,
                    reasons=report.reasons,
                    message=report.status.value,
                )
            )

        if token.is_cancelled:
            cancel_time = events[-1].timestamp if events else datetime.now().astimezone()
            record(
                make_event(
                    BacktestEventType.CANCELLED,
                    cancel_time,
                    security_id=security.security_id,
                    strategy_id=strategy.strategy_id,
                    message="backtest cancelled",
                )
            )

        event_tuple = tuple(events)
        return BacktestRunResult(
            events=event_tuple,
            cancelled=token.is_cancelled,
            checksum=_events_checksum(event_tuple),
        )


def _default_strategy_context(
    config: BacktestConfig,
    security: SecurityRef,
    bar: Bar,
    available_bars: int,
) -> StrategyContext:
    return StrategyContext(
        security_id=security.security_id,
        as_of=bar.observed_at,
        data_snapshot_id=config.data_snapshot_id,
        rule_version=config.rule_version,
        available_bars=available_bars,
    )


def _event_type_for_execution(status: ExecutionStatus) -> BacktestEventType:
    if status is ExecutionStatus.FILLED:
        return BacktestEventType.FILL
    if status is ExecutionStatus.PARTIALLY_FILLED:
        return BacktestEventType.PARTIAL_FILL
    return BacktestEventType.REJECT


def _events_checksum(events: Sequence[BacktestEvent]) -> str:
    payload = [event.to_contract_dict() for event in events]
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()
