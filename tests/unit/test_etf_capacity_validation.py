"""Point-in-time ETF liquidity capacity and impact-cost tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from china_quant_platform.domain import AdjustmentMode, Bar, BarInterval, RecordQualityStatus
from china_quant_platform.strategies.etf_capacity_validation import (
    EtfCapacityStatus,
    EtfTradingSystem,
    assess_etf_capacity_scenario,
    audit_etf_rotation_capacity,
    classify_etf_trading_system,
)
from china_quant_platform.strategies.etf_rotation_validation import (
    EtfRotationRebalanceEvent,
)


def _bars(
    security_id: str,
    *,
    count: int = 35,
    amount: float = 10_000_000.0,
) -> tuple[Bar, ...]:
    result: list[Bar] = []
    current_date = date(2026, 1, 5)
    close = 2.0
    while len(result) < count:
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue
        start_time = datetime.combine(current_date, time(9, 30), tzinfo=UTC)
        end_time = datetime.combine(current_date, time(15), tzinfo=UTC)
        result.append(
            Bar(
                security_id=security_id,
                interval=BarInterval.DAILY,
                start_time=start_time,
                end_time=end_time,
                trade_date=current_date,
                open_price=close,
                high_price=close * 1.01,
                low_price=close * 0.99,
                close_price=close,
                volume=amount / close,
                amount=amount,
                adjustment=AdjustmentMode.FORWARD,
                provider="fixture",
                schema_version="fixture.v1",
                source_time=end_time,
                observed_at=end_time,
                received_at=end_time + timedelta(seconds=1),
                quality_status=RecordQualityStatus.OK,
            )
        )
        current_date += timedelta(days=1)
    return tuple(result)


def _event(bars: tuple[Bar, ...]) -> EtfRotationRebalanceEvent:
    return EtfRotationRebalanceEvent(
        signal_date=bars[24].trade_date,
        execution_date=bars[25].trade_date,
        selected_security_ids=(bars[0].security_id,),
        momentum_scores={bars[0].security_id: 0.12},
        target_position_fraction=0.5,
    )


def test_capacity_passes_small_capital_and_fails_large_capital() -> None:
    security_id = "SSE:513300"
    bars = _bars(security_id)
    report = audit_etf_rotation_capacity(
        {security_id: bars},
        rebalances=(_event(bars),),
    )

    small = assess_etf_capacity_scenario(report, portfolio_capital=100_000)
    large = assess_etf_capacity_scenario(report, portfolio_capital=10_000_000)

    assert small.status is EtfCapacityStatus.PASS
    assert small.max_participation_rate == pytest.approx(0.005)
    assert large.status is EtfCapacityStatus.FAIL
    assert large.max_participation_rate == pytest.approx(0.5)
    assert report.maximum_supported_capital == pytest.approx(400_000)


def test_capacity_uses_only_amount_known_by_signal_date() -> None:
    security_id = "SSE:513300"
    original = _bars(security_id)
    event = _event(original)
    changed_future = tuple(
        bar.model_copy(update={"amount": 1_000.0}) if bar.trade_date > event.signal_date else bar
        for bar in original
    )

    baseline = audit_etf_rotation_capacity(
        {security_id: original},
        rebalances=(event,),
    )
    mutated = audit_etf_rotation_capacity(
        {security_id: changed_future},
        rebalances=(event,),
    )

    assert mutated.reference_scenario == baseline.reference_scenario
    assert mutated.maximum_supported_capital == baseline.maximum_supported_capital


def test_capacity_fails_closed_when_adv_history_is_missing() -> None:
    security_id = "SSE:510300"
    bars = _bars(security_id, count=12)
    event = EtfRotationRebalanceEvent(
        signal_date=bars[10].trade_date,
        execution_date=bars[11].trade_date,
        selected_security_ids=(security_id,),
        momentum_scores={security_id: 0.1},
        target_position_fraction=0.5,
    )

    report = audit_etf_rotation_capacity(
        {security_id: bars},
        rebalances=(event,),
    )

    assert report.reference_scenario.status is EtfCapacityStatus.MISSING
    assert report.reference_scenario.missing_observation_count == 1
    assert "缺少信号日前20日" in report.reference_scenario.reasons[0]


def test_etf_trading_system_classification_is_shared_and_conservative() -> None:
    assert (
        classify_etf_trading_system("SSE:513300", asset_bucket="overseas_equity")
        is EtfTradingSystem.T_PLUS_ZERO
    )
    assert (
        classify_etf_trading_system("SSE:511010", asset_bucket="bond")
        is EtfTradingSystem.T_PLUS_ZERO
    )
    assert (
        classify_etf_trading_system("SZSE:159915", asset_bucket="growth_cn")
        is EtfTradingSystem.T_PLUS_ONE
    )
    assert classify_etf_trading_system("NASDAQ:QQQ") is EtfTradingSystem.UNKNOWN
