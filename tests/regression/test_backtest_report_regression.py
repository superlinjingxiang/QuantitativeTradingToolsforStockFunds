"""Deterministic backtest report regression fixture."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from china_quant_platform.backtest import BacktestEvent, BacktestEventType
from china_quant_platform.domain import BacktestConfig
from china_quant_platform.reporting import (
    BacktestReportBuilder,
    EquityPoint,
    calculate_calibration,
    export_html_report,
    export_trades_csv,
)


def config() -> BacktestConfig:
    return BacktestConfig(
        strategy_id="strategy.demo",
        strategy_version="v1",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        initial_cash=100_000,
        data_snapshot_id="snapshot-report-001",
        rule_version="rules-cn-v1",
        seed=7,
    )


def equity_curve() -> tuple[EquityPoint, ...]:
    return (
        EquityPoint(day=date(2026, 1, 1), net_asset_value=100_000),
        EquityPoint(day=date(2026, 1, 2), net_asset_value=101_000),
        EquityPoint(day=date(2026, 1, 3), net_asset_value=100_000),
        EquityPoint(day=date(2026, 1, 4), net_asset_value=103_000),
    )


def events() -> tuple[BacktestEvent, ...]:
    timestamp = datetime(2026, 1, 2, 9, 30, tzinfo=UTC)
    return (
        BacktestEvent(
            sequence=1,
            event_id="event-000001",
            event_type=BacktestEventType.FILL,
            timestamp=timestamp,
            security_id="SSE:600519",
            strategy_id="strategy.demo",
            order_id="order-001",
            quantity=100,
            filled_quantity=100,
            price=10.0,
            notional=1_000.0,
            total_fees=5.0,
            slippage_cost=1.0,
            spread_cost=0.5,
        ),
        BacktestEvent(
            sequence=2,
            event_id="event-000002",
            event_type=BacktestEventType.REJECT,
            timestamp=timestamp,
            security_id="SSE:600519",
            strategy_id="strategy.demo",
            order_id="order-002",
            quantity=50,
            filled_quantity=0,
            price=10.0,
            reasons=("Order quantity must be a multiple of lot_size 100.",),
        ),
    )


def test_backtest_report_metrics_exports_and_checksum_are_deterministic() -> None:
    report = BacktestReportBuilder().build(
        config=config(),
        equity_curve=equity_curve(),
        events=events(),
        code_version="test-build",
        event_checksum="events-checksum-001",
        probabilities=(0.8, 0.2),
        outcomes=(1, 0),
    )
    report_again = BacktestReportBuilder().build(
        config=config(),
        equity_curve=equity_curve(),
        events=events(),
        code_version="test-build",
        event_checksum="events-checksum-001",
        probabilities=(0.8, 0.2),
        outcomes=(1, 0),
    )

    assert report.performance.total_return == pytest.approx(0.03)
    assert report.performance.max_drawdown == pytest.approx(100_000 / 101_000 - 1.0)
    assert report.costs.total_notional == pytest.approx(1_000.0)
    assert report.costs.total_fees == pytest.approx(5.0)
    assert report.costs.slippage_cost == pytest.approx(1.0)
    assert report.calibration.brier_score == pytest.approx(0.04)
    assert report.checksum == report_again.checksum
    assert report.checksum == "cedc0dd803c8b279fd68cf5e2b4514bc5e7c053d9dcf634db439392b7bf9cdee"

    csv_output = export_trades_csv(report)
    assert "event_id,timestamp,event_type,security_id" in csv_output
    assert "event-000001" in csv_output
    assert "Order quantity must be a multiple" in csv_output

    html_output = export_html_report(report)
    assert "strategy.demo" in html_output
    assert report.checksum in html_output


def test_calibration_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        calculate_calibration((0.5,), ())
