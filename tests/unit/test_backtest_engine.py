"""Event-driven backtest kernel tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from china_quant_platform.backtest import (
    BacktestCancellationToken,
    BacktestClock,
    BacktestEngine,
    BacktestEvent,
    BacktestEventLoop,
    BacktestEventType,
    DeterministicExecutionSimulator,
    ExecutionStatus,
    OrderIntent,
)
from china_quant_platform.domain import (
    AdjustmentMode,
    AssetType,
    BacktestConfig,
    Bar,
    BarInterval,
    Currency,
    Exchange,
    RecordQualityStatus,
    RuleReviewStatus,
    SecurityRef,
    SecurityRule,
    SecurityStatus,
)
from china_quant_platform.rules import InMemoryRuleRepository, MarketRuleEngine, OrderSide
from china_quant_platform.strategies import (
    DriverDirection,
    Explanation,
    ExplanationDriver,
    RawSignal,
    RawSignalIntent,
    StrategyCondition,
    StrategyContext,
    WarmupSpec,
)


def stock_rule() -> SecurityRule:
    data: dict[str, object] = {
        "rule_id": "sse-stock-v1",
        "version": "v1",
        "exchange": Exchange.SSE,
        "asset_type": AssetType.STOCK,
        "effective_from": date(2020, 1, 1),
        "lot_size": 100,
        "tick_size": 0.01,
        "intraday_round_trip": False,
        "source": "fixture exchange rule",
        "review_status": RuleReviewStatus.APPROVED,
        "limit_up_pct": 0.10,
        "limit_down_pct": 0.10,
        "commission_rate": 0.0003,
        "min_commission": 5.0,
        "transfer_fee_rate": 0.00001,
        "stamp_tax_rate": 0.0005,
    }
    return SecurityRule.model_validate(data)


def security() -> SecurityRef:
    return SecurityRef(
        security_id="SSE:600519",
        symbol="600519",
        name="fixture stock",
        asset_type=AssetType.STOCK,
        exchange=Exchange.SSE,
        currency=Currency.CNY,
        listed_date=date(2001, 1, 1),
        status_date=date(2026, 1, 5),
        status=SecurityStatus.ACTIVE,
    )


def make_bar(index: int, *, close: float = 10.0) -> Bar:
    start = datetime(2026, 1, 5, 9, 30, tzinfo=UTC) + timedelta(days=index)
    end = datetime(2026, 1, 5, 15, 0, tzinfo=UTC) + timedelta(days=index)
    return Bar(
        security_id="SSE:600519",
        interval=BarInterval.DAILY,
        start_time=start,
        end_time=end,
        trade_date=start.date(),
        open_price=close,
        high_price=close,
        low_price=close,
        close_price=close,
        volume=1_000,
        amount=close * 1_000,
        adjustment=AdjustmentMode.NONE,
        provider="fixture",
        schema_version="v1",
        source_time=end,
        observed_at=end,
        received_at=end + timedelta(minutes=1),
        quality_status=RecordQualityStatus.OK,
    )


def config() -> BacktestConfig:
    return BacktestConfig(
        strategy_id="strategy.demo",
        strategy_version="v1",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        initial_cash=1_000_000,
        data_snapshot_id="snapshot-001",
        rule_version="rules-cn-v1",
        seed=7,
    )


def condition(name: str = "trend_available") -> StrategyCondition:
    return StrategyCondition(
        name=name,
        description=f"{name} is visible at signal time.",
        is_satisfied=True,
    )


class DemoStrategy:
    strategy_id = "strategy.demo"
    version = "v1"
    horizon = 5

    def warmup_requirements(self) -> WarmupSpec:
        return WarmupSpec(minimum_bars=1)

    def generate_signal(self, strategy_context: StrategyContext) -> RawSignal:
        return RawSignal(
            strategy_id=self.strategy_id,
            strategy_version=self.version,
            security_id=strategy_context.security_id,
            generated_at=strategy_context.as_of,
            valid_until=strategy_context.as_of + timedelta(days=1),
            horizon=self.horizon,
            intent=RawSignalIntent.BUY_BIAS,
            score=0.4,
            confidence=0.8,
            data_snapshot_id=strategy_context.data_snapshot_id,
            model_version="model-demo-v1",
            applicable_conditions=(condition(),),
            invalidation_conditions=(condition("trend_breaks"),),
            factor_values={"momentum.ret_20d.v1": 0.1},
        )

    def explain(self, strategy_context: StrategyContext, signal: RawSignal) -> Explanation:
        assert strategy_context.security_id == signal.security_id
        return Explanation(
            strategy_id=signal.strategy_id,
            strategy_version=signal.strategy_version,
            security_id=signal.security_id,
            generated_at=signal.generated_at,
            data_snapshot_id=signal.data_snapshot_id,
            summary="Demo raw signal requires downstream gates.",
            drivers=(
                ExplanationDriver(
                    name="momentum.ret_20d.v1",
                    value=0.1,
                    contribution=0.4,
                    direction=DriverDirection.POSITIVE,
                    description="Momentum is positive.",
                ),
            ),
            applicable_conditions=signal.applicable_conditions,
            invalidation_conditions=signal.invalidation_conditions,
        )


def rule_engine() -> MarketRuleEngine:
    return MarketRuleEngine(InMemoryRuleRepository([stock_rule()]))


def buy_policy(
    signal: RawSignal,
    strategy_context: StrategyContext,
    bar: Bar,
    clock: BacktestClock,
    *,
    quantity: int = 100,
) -> OrderIntent:
    created_at = clock.next_session_open(signal.generated_at)
    return OrderIntent(
        order_id=f"order-{strategy_context.security_id}-{created_at.date().isoformat()}",
        security_id=strategy_context.security_id,
        side=OrderSide.BUY,
        quantity=quantity,
        price=bar.close_price,
        created_at=created_at,
        trade_date=created_at.date(),
        source_signal_id=f"{signal.strategy_id}:{signal.generated_at.isoformat()}",
        strategy_id=signal.strategy_id,
    )


def test_event_loop_orders_by_time_priority_and_sequence() -> None:
    timestamp = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
    loop = BacktestEventLoop()
    loop.schedule(
        BacktestEvent(
            sequence=2,
            event_id="event-000002",
            event_type=BacktestEventType.AUDIT,
            timestamp=timestamp,
        )
    )
    loop.schedule(
        BacktestEvent(
            sequence=1,
            event_id="event-000001",
            event_type=BacktestEventType.MARKET,
            timestamp=timestamp,
        )
    )

    first = loop.pop_next()
    second = loop.pop_next()
    assert first is not None
    assert second is not None
    assert first.event_type is BacktestEventType.MARKET
    assert second.event_type is BacktestEventType.AUDIT
    assert loop.pop_next() is None


def test_backtest_engine_runs_strategy_after_market_and_executes_next_session() -> None:
    engine = BacktestEngine(rule_engine=rule_engine())
    bar = make_bar(0)

    result = engine.run(
        config=config(),
        security=security(),
        bars=(bar,),
        strategy=DemoStrategy(),
        order_policy=lambda signal, context, current_bar, clock: buy_policy(
            signal,
            context,
            current_bar,
            clock,
        ),
    )
    result_again = engine.run(
        config=config(),
        security=security(),
        bars=(bar,),
        strategy=DemoStrategy(),
        order_policy=lambda signal, context, current_bar, clock: buy_policy(
            signal,
            context,
            current_bar,
            clock,
        ),
    )

    assert tuple(event.event_type for event in result.events) == (
        BacktestEventType.MARKET,
        BacktestEventType.STRATEGY_EVALUATION,
        BacktestEventType.SIGNAL,
        BacktestEventType.ORDER,
        BacktestEventType.FILL,
    )
    signal_event = result.events[2]
    order_event = result.events[3]
    assert order_event.timestamp > signal_event.timestamp
    assert order_event.timestamp.time().isoformat() == "09:30:00"
    assert result.events[4].execution_status is ExecutionStatus.FILLED
    assert result.checksum == result_again.checksum


def test_backtest_engine_rejects_orders_that_fail_market_rules() -> None:
    engine = BacktestEngine(rule_engine=rule_engine())

    result = engine.run(
        config=config(),
        security=security(),
        bars=(make_bar(0),),
        strategy=DemoStrategy(),
        order_policy=lambda signal, context, current_bar, clock: buy_policy(
            signal,
            context,
            current_bar,
            clock,
            quantity=50,
        ),
    )

    reject_event = result.events[-1]
    assert reject_event.event_type is BacktestEventType.REJECT
    assert reject_event.execution_status is ExecutionStatus.REJECTED
    assert "Order quantity must be a multiple of lot_size 100." in reject_event.reasons


def test_backtest_engine_supports_partial_fills() -> None:
    engine = BacktestEngine(
        rule_engine=rule_engine(),
        execution_simulator=DeterministicExecutionSimulator(max_fill_quantity_per_order=100),
    )

    result = engine.run(
        config=config(),
        security=security(),
        bars=(make_bar(0),),
        strategy=DemoStrategy(),
        order_policy=lambda signal, context, current_bar, clock: buy_policy(
            signal,
            context,
            current_bar,
            clock,
            quantity=300,
        ),
    )

    partial_event = result.events[-1]
    assert partial_event.event_type is BacktestEventType.PARTIAL_FILL
    assert partial_event.execution_status is ExecutionStatus.PARTIALLY_FILLED
    assert partial_event.filled_quantity == 100


def test_backtest_engine_supports_cancellation() -> None:
    engine = BacktestEngine(rule_engine=rule_engine())
    token = BacktestCancellationToken()

    def cancel_after_market(
        event: BacktestEvent, cancellation_token: BacktestCancellationToken
    ) -> None:
        if event.event_type is BacktestEventType.MARKET:
            cancellation_token.cancel()

    result = engine.run(
        config=config(),
        security=security(),
        bars=(make_bar(0),),
        strategy=DemoStrategy(),
        order_policy=lambda signal, context, current_bar, clock: buy_policy(
            signal,
            context,
            current_bar,
            clock,
        ),
        cancellation_token=token,
        on_event=cancel_after_market,
    )

    assert result.cancelled is True
    assert tuple(event.event_type for event in result.events) == (
        BacktestEventType.MARKET,
        BacktestEventType.CANCELLED,
    )


def test_backtest_engine_rejects_same_timestamp_order_policy() -> None:
    engine = BacktestEngine(rule_engine=rule_engine())

    def leaking_policy(
        signal: RawSignal,
        strategy_context: StrategyContext,
        bar: Bar,
        _clock: BacktestClock,
    ) -> OrderIntent:
        return OrderIntent(
            order_id="order-leak",
            security_id=strategy_context.security_id,
            side=OrderSide.BUY,
            quantity=100,
            price=bar.close_price,
            created_at=signal.generated_at,
            trade_date=signal.generated_at.date(),
            source_signal_id="signal-leak",
            strategy_id=signal.strategy_id,
        )

    with pytest.raises(ValueError, match="order.created_at must be later"):
        engine.run(
            config=config(),
            security=security(),
            bars=(make_bar(0),),
            strategy=DemoStrategy(),
            order_policy=leaking_policy,
        )
