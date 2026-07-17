"""ETF rotation portfolio validation tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from china_quant_platform.domain import AdjustmentMode, Bar, BarInterval, RecordQualityStatus
from china_quant_platform.strategies.etf_rotation_validation import (
    EtfRotationBacktestConfig,
    EtfRotationValidationStatus,
    run_etf_rotation_backtest,
    validate_etf_rotation_strategy,
)


def _bars(security_id: str, *, rank: int, count: int = 900) -> tuple[Bar, ...]:
    result: list[Bar] = []
    current_date = date(2022, 1, 3)
    close = 1.0
    index = 0
    while len(result) < count:
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue
        base_return = 0.0016 - rank * 0.00018
        alternating_noise = 0.009 if index % 2 == 0 else -0.008
        daily_return = base_return + alternating_noise
        open_price = close * (1.0 + daily_return * 0.2)
        next_close = close * (1.0 + daily_return)
        start_time = datetime.combine(current_date, time(9, 30), tzinfo=UTC)
        end_time = datetime.combine(current_date, time(15, 0), tzinfo=UTC)
        result.append(
            Bar(
                security_id=security_id,
                interval=BarInterval.DAILY,
                start_time=start_time,
                end_time=end_time,
                trade_date=current_date,
                open_price=open_price,
                high_price=max(open_price, next_close) * 1.005,
                low_price=min(open_price, next_close) * 0.995,
                close_price=next_close,
                volume=2_000_000,
                amount=2_000_000 * next_close,
                adjustment=AdjustmentMode.FORWARD,
                provider="fixture",
                schema_version="fixture.v1",
                source_time=end_time,
                observed_at=end_time,
                received_at=end_time + timedelta(seconds=1),
                quality_status=RecordQualityStatus.OK,
            )
        )
        close = next_close
        index += 1
        current_date += timedelta(days=1)
    return tuple(result)


@pytest.fixture
def etf_bars() -> dict[str, tuple[Bar, ...]]:
    return {f"SSE:51{rank:04d}": _bars(f"SSE:51{rank:04d}", rank=rank) for rank in range(10)}


def test_rotation_uses_only_prior_close_and_executes_next_open(
    etf_bars: dict[str, tuple[Bar, ...]],
) -> None:
    security_ids = tuple(etf_bars)
    result = run_etf_rotation_backtest(etf_bars, security_ids=security_ids)

    first = result.rebalances[0]
    assert first.signal_date < first.execution_date
    assert first.selected_security_ids == security_ids[:2]
    expected_score = (
        etf_bars[security_ids[0]][252].close_price / etf_bars[security_ids[0]][0].close_price - 1.0
    )
    assert first.momentum_scores[security_ids[0]] == pytest.approx(expected_score)


def test_rotation_applies_volatility_target_and_position_bounds(
    etf_bars: dict[str, tuple[Bar, ...]],
) -> None:
    result = run_etf_rotation_backtest(etf_bars, security_ids=tuple(etf_bars))

    assert result.rebalances
    assert all(
        0.25 <= event.target_position_fraction <= 1.0
        for event in result.rebalances
        if event.selected_security_ids
    )
    assert 0.25 <= result.average_position_fraction <= 1.0


def test_stress_cost_cannot_improve_rotation_return(
    etf_bars: dict[str, tuple[Bar, ...]],
) -> None:
    identifiers = tuple(etf_bars)
    base = run_etf_rotation_backtest(etf_bars, security_ids=identifiers)
    stress = run_etf_rotation_backtest(
        etf_bars,
        security_ids=identifiers,
        config=EtfRotationBacktestConfig(round_trip_cost_bps=45.0),
    )

    assert stress.total_return < base.total_return
    assert stress.round_trip_cost_bps == 45.0


def test_validation_requires_return_risk_cost_and_rolling_evidence(
    etf_bars: dict[str, tuple[Bar, ...]],
) -> None:
    report = validate_etf_rotation_strategy(etf_bars, security_ids=tuple(etf_bars))

    assert report.status in {
        EtfRotationValidationStatus.PASS,
        EtfRotationValidationStatus.WATCH,
    }
    assert report.base.total_return > 0
    assert report.stress.total_return > 0
    assert report.walk_forward_folds
    assert all(fold.evaluation_start < fold.evaluation_end for fold in report.walk_forward_folds)


def test_validation_does_not_pass_with_only_one_walk_forward_fold(
    etf_bars: dict[str, tuple[Bar, ...]],
) -> None:
    evaluation_start = etf_bars[next(iter(etf_bars))][648].trade_date

    report = validate_etf_rotation_strategy(
        etf_bars,
        security_ids=tuple(etf_bars),
        evaluation_start=evaluation_start,
    )

    assert len(report.walk_forward_folds) == 1
    assert report.base.total_return > 0
    assert report.status is EtfRotationValidationStatus.WATCH
    assert "walk_forward_folds=1/3" in report.notes
