"""Paper-trading simulation broker tests."""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime, timedelta

import pytest

from china_quant_platform.backtest import DeterministicExecutionSimulator, OrderIntent
from china_quant_platform.domain import (
    AssetType,
    Currency,
    DataHealth,
    DataHealthStatus,
    Exchange,
    Quote,
    RecordQualityStatus,
    RuleReviewStatus,
    SecurityRef,
    SecurityRule,
    SecurityStatus,
)
from china_quant_platform.rules import InMemoryRuleRepository, MarketRuleEngine, OrderSide
from china_quant_platform.simulation import (
    REAL_ORDER_SUBMISSION_ENABLED,
    SimulationBroker,
    SimulationBrokerConfig,
    SimulationOrderStatus,
    restore_simulation_state,
    simulation_state_checksum,
)


def as_of(hour: int = 9, minute: int = 31) -> datetime:
    return datetime(2026, 6, 29, hour, minute, tzinfo=UTC)


def stock_rule() -> SecurityRule:
    return SecurityRule.model_validate(
        {
            "rule_id": "sse-stock-v1",
            "version": "rules-cn-v1",
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
    )


def rule_engine() -> MarketRuleEngine:
    return MarketRuleEngine(InMemoryRuleRepository([stock_rule()]))


def security() -> SecurityRef:
    return SecurityRef(
        security_id="SSE:600519",
        symbol="600519",
        name="fixture stock",
        asset_type=AssetType.STOCK,
        exchange=Exchange.SSE,
        currency=Currency.CNY,
        listed_date=date(2001, 1, 1),
        status_date=date(2026, 6, 29),
        status=SecurityStatus.ACTIVE,
    )


def quote(latest_price: float = 10.0, previous_close: float = 10.0) -> Quote:
    source = as_of()
    return Quote(
        security_id="SSE:600519",
        latest_price=latest_price,
        previous_close=previous_close,
        open_price=previous_close,
        high_price=max(latest_price, previous_close),
        low_price=min(latest_price, previous_close),
        volume=100_000,
        amount=latest_price * 100_000,
        provider="fixture",
        schema_version="v1",
        source_time=source,
        observed_at=source,
        received_at=source + timedelta(seconds=1),
        quality_status=RecordQualityStatus.OK,
    )


def healthy_data() -> DataHealth:
    return DataHealth(status=DataHealthStatus.HEALTHY, block_signal=False, as_of=as_of())


def stale_data() -> DataHealth:
    return DataHealth(
        status=DataHealthStatus.STALE,
        block_signal=True,
        as_of=as_of(),
        issues=("realtime disconnected",),
    )


def order(
    *,
    order_id: str = "order-001",
    side: OrderSide = OrderSide.BUY,
    quantity: int = 100,
    price: float = 10.0,
) -> OrderIntent:
    created_at = as_of()
    return OrderIntent(
        order_id=order_id,
        security_id="SSE:600519",
        side=side,
        quantity=quantity,
        price=price,
        created_at=created_at,
        trade_date=created_at.date(),
        source_signal_id="strategy.demo:signal-001",
        strategy_id="strategy.demo",
    )


def broker(
    *,
    execution_simulator: DeterministicExecutionSimulator | None = None,
) -> SimulationBroker:
    return SimulationBroker(
        config=SimulationBrokerConfig(account_id="paper-001"),
        rule_engine=rule_engine(),
        initial_cash=100_000.0,
        execution_simulator=execution_simulator,
    )


def test_simulation_broker_fills_order_updates_portfolio_pnl_and_audit() -> None:
    paper = broker()

    result = paper.submit_order(
        order=order(),
        security=security(),
        quote=quote(),
        data_health=healthy_data(),
    )

    assert result.order_record.status is SimulationOrderStatus.FILLED
    assert result.execution_record.report.filled_quantity == 100
    assert result.reconciliation.balanced is True
    position = result.state.portfolio.positions["SSE:600519"]
    assert position.quantity == 100
    assert position.sellable_quantity == 0
    assert result.state.metrics.net_asset_value == pytest.approx(
        result.state.portfolio.net_asset_value
    )
    assert result.state.orders[0].order.order_id == "order-001"
    assert result.state.deviations[0].source_signal_id == "strategy.demo:signal-001"

    marked = paper.mark_to_market(prices={"SSE:600519": 11.0}, updated_at=as_of(15, 0))
    assert marked.metrics.unrealized_pnl > 0


def test_stale_data_blocks_simulation_order_without_position_change() -> None:
    paper = broker()

    result = paper.submit_order(
        order=order(),
        security=security(),
        quote=quote(),
        data_health=stale_data(),
    )

    assert result.order_record.status is SimulationOrderStatus.REJECTED
    assert "realtime disconnected" in result.order_record.reasons[0]
    assert result.state.portfolio.positions == {}
    assert result.state.portfolio.cash == 100_000.0


def test_same_day_sell_is_rejected_by_t_plus_one_sellable_quantity() -> None:
    paper = broker()
    paper.submit_order(
        order=order(order_id="buy-001"),
        security=security(),
        quote=quote(),
        data_health=healthy_data(),
    )

    result = paper.submit_order(
        order=order(order_id="sell-001", side=OrderSide.SELL),
        security=security(),
        quote=quote(),
        data_health=healthy_data(),
    )

    assert result.order_record.status is SimulationOrderStatus.REJECTED
    assert "Sell quantity exceeds currently sellable quantity." in result.order_record.reasons
    assert result.state.portfolio.positions["SSE:600519"].quantity == 100


def test_partial_fill_records_signal_execution_deviation() -> None:
    paper = broker(
        execution_simulator=DeterministicExecutionSimulator(max_fill_quantity_per_order=100)
    )

    result = paper.submit_order(
        order=order(quantity=300),
        security=security(),
        quote=quote(),
        data_health=healthy_data(),
    )

    assert result.order_record.status is SimulationOrderStatus.PARTIALLY_FILLED
    assert result.deviation.filled_ratio == pytest.approx(1 / 3)
    assert result.deviation.threshold_breached is True
    assert result.state.portfolio.positions["SSE:600519"].quantity == 100


def test_simulation_state_can_be_exported_and_restored_after_restart() -> None:
    paper = broker()
    paper.submit_order(
        order=order(),
        security=security(),
        quote=quote(),
        data_health=healthy_data(),
    )
    payload = paper.export_state()
    restored_state = restore_simulation_state(payload)
    restored = SimulationBroker.from_snapshot(
        payload=payload,
        config=SimulationBrokerConfig(account_id="paper-001"),
        rule_engine=rule_engine(),
        initial_cash=100_000.0,
    )

    assert restored.state == restored_state
    assert restored.state.portfolio.positions["SSE:600519"].quantity == 100
    assert simulation_state_checksum(restored.state) == simulation_state_checksum(paper.state)


def test_simulation_broker_exposes_no_real_order_submission_path() -> None:
    method_names = {
        name
        for name, member in inspect.getmembers(SimulationBroker, predicate=inspect.isfunction)
        if not name.startswith("_")
    }

    assert REAL_ORDER_SUBMISSION_ENABLED is False
    assert "submit_order" in method_names
    assert all("real" not in name.lower() for name in method_names)
