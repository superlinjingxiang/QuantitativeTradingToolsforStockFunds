"""Portfolio accounting and risk gate tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from china_quant_platform.backtest import (
    ExecutionCostBreakdown,
    ExecutionReport,
    ExecutionStatus,
    OrderIntent,
)
from china_quant_platform.portfolio import PortfolioEngine, PortfolioState, Position
from china_quant_platform.risk import RiskEngine, RiskLimitConfig, position_size_by_risk_budget
from china_quant_platform.rules import OrderSide


def order(
    *,
    side: OrderSide,
    quantity: int,
    price: float,
    security_id: str = "SSE:600519",
) -> OrderIntent:
    created_at = datetime(2026, 1, 6, 9, 30, tzinfo=UTC)
    return OrderIntent(
        order_id=f"order-{side.value}-{security_id}",
        security_id=security_id,
        side=side,
        quantity=quantity,
        price=price,
        created_at=created_at,
        trade_date=date(2026, 1, 6),
        source_signal_id="signal-001",
        strategy_id="strategy.demo",
    )


def report(
    *,
    quantity: int,
    price: float,
    total_cost: float,
    order_id: str,
) -> ExecutionReport:
    return ExecutionReport(
        order_id=order_id,
        status=ExecutionStatus.FILLED,
        filled_quantity=quantity,
        fill_price=price,
        notional=quantity * price,
        costs=ExecutionCostBreakdown(
            commission=total_cost,
            total=total_cost,
        ),
    )


def test_portfolio_engine_applies_buy_and_reconciles_nav() -> None:
    engine = PortfolioEngine()
    portfolio = PortfolioState(cash=100_000.0)
    buy_order = order(side=OrderSide.BUY, quantity=100, price=10.0)
    buy_report = report(
        quantity=100,
        price=10.0,
        total_cost=5.0,
        order_id=buy_order.order_id,
    )

    updated = engine.apply_execution(
        portfolio=portfolio,
        order=buy_order,
        report=buy_report,
    )
    position = updated.positions["SSE:600519"]

    assert updated.cash == pytest.approx(98_995.0)
    assert position.quantity == 100
    assert position.sellable_quantity == 0
    assert position.average_cost == pytest.approx(10.05)
    marked = updated.mark_to_market({"SSE:600519": 11.0})
    reconciliation = marked.reconcile(expected_net_asset_value=100_095.0)
    assert reconciliation.balanced is True
    assert reconciliation.net_asset_value == pytest.approx(100_095.0)


def test_portfolio_engine_applies_sell_and_blocks_unsellable_quantity() -> None:
    engine = PortfolioEngine()
    portfolio = PortfolioState(
        cash=0.0,
        positions={
            "SSE:600519": Position(
                security_id="SSE:600519",
                quantity=200,
                sellable_quantity=100,
                average_cost=10.0,
                last_price=12.0,
            )
        },
    )
    sell_order = order(side=OrderSide.SELL, quantity=100, price=12.0)
    sell_report = report(
        quantity=100,
        price=12.0,
        total_cost=2.0,
        order_id=sell_order.order_id,
    )

    updated = engine.apply_execution(
        portfolio=portfolio,
        order=sell_order,
        report=sell_report,
    )
    position = updated.positions["SSE:600519"]

    assert updated.cash == pytest.approx(1_198.0)
    assert position.quantity == 100
    assert position.sellable_quantity == 0
    assert position.realized_pnl == pytest.approx(198.0)

    too_large_report = report(
        quantity=150,
        price=12.0,
        total_cost=2.0,
        order_id=sell_order.order_id,
    )
    with pytest.raises(ValueError, match="sellable_quantity"):
        engine.apply_execution(portfolio=portfolio, order=sell_order, report=too_large_report)


def test_risk_engine_flags_concentration_cash_liquidity_drawdown_and_correlation() -> None:
    portfolio = PortfolioState(
        cash=10_000.0,
        positions={
            "SSE:600000": Position(
                security_id="SSE:600000",
                quantity=100,
                sellable_quantity=100,
                average_cost=50.0,
                last_price=50.0,
            )
        },
    )
    risk = RiskEngine(
        RiskLimitConfig(
            max_single_position_weight=0.4,
            max_total_exposure=0.9,
            max_drawdown=0.2,
            max_order_participation_rate=0.1,
            min_cash_buffer=0.05,
            max_pairwise_correlation=0.8,
        )
    )
    buy_order = order(side=OrderSide.BUY, quantity=1_000, price=10.0)

    result = risk.evaluate_order(
        portfolio=portfolio,
        order=buy_order,
        latest_prices={"SSE:600519": 10.0, "SSE:600000": 50.0},
        average_daily_volume={"SSE:600519": 5_000},
        peak_net_asset_value=20_000.0,
        correlations={("SSE:600519", "SSE:600000"): 0.95},
    )

    assert result.allowed is False
    assert "Single position weight exceeds limit." in result.reasons
    assert "Total exposure exceeds limit." in result.reasons
    assert "Cash buffer would fall below limit." in result.reasons
    assert "Order quantity exceeds liquidity participation limit." in result.reasons
    assert "Portfolio drawdown exceeds limit." in result.reasons
    assert "Pairwise correlation exceeds limit." in result.reasons


def test_position_size_by_risk_budget_rounds_to_lot_size() -> None:
    assert (
        position_size_by_risk_budget(
            net_asset_value=100_000,
            entry_price=10.0,
            stop_price=9.0,
            risk_budget_pct=0.01,
            lot_size=100,
        )
        == 1_000
    )

    with pytest.raises(ValueError, match="entry_price"):
        position_size_by_risk_budget(
            net_asset_value=100_000,
            entry_price=9.0,
            stop_price=10.0,
            risk_budget_pct=0.01,
        )
