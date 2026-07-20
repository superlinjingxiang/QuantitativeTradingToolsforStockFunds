"""ETF rotation portfolio validation tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from china_quant_platform.domain import AdjustmentMode, Bar, BarInterval, RecordQualityStatus
from china_quant_platform.strategies.etf_rotation_lab import _compact_rotation_report
from china_quant_platform.strategies.etf_rotation_validation import (
    EtfExposureScalingModel,
    EtfMomentumSignalModel,
    EtfRotationBacktestConfig,
    EtfRotationValidationStatus,
    build_current_etf_rotation_allocation,
    run_etf_rotation_backtest,
    validate_etf_rotation_strategy,
)


def _bars(
    security_id: str,
    *,
    rank: int,
    count: int = 900,
    noise_scale: float = 1.0,
) -> tuple[Bar, ...]:
    result: list[Bar] = []
    current_date = date(2022, 1, 3)
    close = 1.0
    index = 0
    while len(result) < count:
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue
        base_return = 0.0016 - rank * 0.00018
        alternating_noise = (0.009 if index % 2 == 0 else -0.008) * noise_scale
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


def test_research_candidates_are_not_the_production_default() -> None:
    config = EtfRotationBacktestConfig()

    assert config.signal_model is EtfMomentumSignalModel.SINGLE_HORIZON
    assert config.exposure_model is EtfExposureScalingModel.INVERSE_VOLATILITY


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


def test_inverse_variance_reduces_high_volatility_exposure_without_changing_rank() -> None:
    high_volatility_bars = {
        f"SSE:51{rank:04d}": _bars(
            f"SSE:51{rank:04d}",
            rank=rank,
            noise_scale=3.0,
        )
        for rank in range(10)
    }
    security_ids = tuple(high_volatility_bars)
    baseline = run_etf_rotation_backtest(
        high_volatility_bars,
        security_ids=security_ids,
    )
    candidate = run_etf_rotation_backtest(
        high_volatility_bars,
        security_ids=security_ids,
        config=EtfRotationBacktestConfig(exposure_model=EtfExposureScalingModel.INVERSE_VARIANCE),
    )

    baseline_first = baseline.rebalances[0]
    candidate_first = candidate.rebalances[0]
    assert candidate_first.selected_security_ids == baseline_first.selected_security_ids
    assert candidate_first.momentum_scores == baseline_first.momentum_scores
    assert candidate_first.target_position_fraction < baseline_first.target_position_fraction
    assert candidate_first.target_position_fraction == pytest.approx(
        max(0.25, baseline_first.target_position_fraction**2)
    )


def test_inverse_variance_does_not_leverage_low_volatility_assets(
    etf_bars: dict[str, tuple[Bar, ...]],
) -> None:
    security_ids = tuple(etf_bars)
    baseline = run_etf_rotation_backtest(etf_bars, security_ids=security_ids)
    candidate = run_etf_rotation_backtest(
        etf_bars,
        security_ids=security_ids,
        config=EtfRotationBacktestConfig(exposure_model=EtfExposureScalingModel.INVERSE_VARIANCE),
    )

    assert baseline.rebalances[0].target_position_fraction == pytest.approx(1.0)
    assert candidate.rebalances[0].target_position_fraction == pytest.approx(1.0)


def test_inverse_variance_first_allocation_does_not_read_future_bars(
    etf_bars: dict[str, tuple[Bar, ...]],
) -> None:
    config = EtfRotationBacktestConfig(exposure_model=EtfExposureScalingModel.INVERSE_VARIANCE)
    security_ids = tuple(etf_bars)
    baseline = run_etf_rotation_backtest(
        etf_bars,
        security_ids=security_ids,
        config=config,
    )
    mutated = {
        security_id: tuple(
            bar
            if index <= 252
            else bar.model_copy(
                update={
                    "open_price": bar.open_price * 5,
                    "high_price": bar.high_price * 5,
                    "low_price": bar.low_price * 5,
                    "close_price": bar.close_price * 5,
                }
            )
            for index, bar in enumerate(bars)
        )
        for security_id, bars in etf_bars.items()
    }
    changed = run_etf_rotation_backtest(
        mutated,
        security_ids=security_ids,
        config=config,
    )

    assert changed.rebalances[0] == baseline.rebalances[0]


def test_dual_horizon_requires_positive_126_and_252_day_momentum(
    etf_bars: dict[str, tuple[Bar, ...]],
) -> None:
    identifiers = tuple(etf_bars)
    conflicted_security = identifiers[0]
    conflicted_bars = list(etf_bars[conflicted_security])
    signal_close = conflicted_bars[252].close_price
    conflicted_bars[126] = conflicted_bars[126].model_copy(
        update={
            "open_price": signal_close * 1.05,
            "high_price": signal_close * 1.06,
            "low_price": signal_close * 1.04,
            "close_price": signal_close * 1.05,
        }
    )
    candidate_bars = dict(etf_bars)
    candidate_bars[conflicted_security] = tuple(conflicted_bars)

    baseline = run_etf_rotation_backtest(
        candidate_bars,
        security_ids=identifiers,
    )
    consensus = run_etf_rotation_backtest(
        candidate_bars,
        security_ids=identifiers,
        config=EtfRotationBacktestConfig(
            signal_model=EtfMomentumSignalModel.DUAL_HORIZON_CONSENSUS
        ),
    )

    assert conflicted_security in baseline.rebalances[0].selected_security_ids
    assert conflicted_security not in consensus.rebalances[0].selected_security_ids


def test_dual_horizon_first_signal_does_not_read_future_bars(
    etf_bars: dict[str, tuple[Bar, ...]],
) -> None:
    config = EtfRotationBacktestConfig(signal_model=EtfMomentumSignalModel.DUAL_HORIZON_CONSENSUS)
    identifiers = tuple(etf_bars)
    baseline = run_etf_rotation_backtest(
        etf_bars,
        security_ids=identifiers,
        config=config,
    )
    mutated = {
        security_id: tuple(
            bar
            if index <= 252
            else bar.model_copy(
                update={
                    "open_price": bar.open_price * 5,
                    "high_price": bar.high_price * 5,
                    "low_price": bar.low_price * 5,
                    "close_price": bar.close_price * 5,
                }
            )
            for index, bar in enumerate(bars)
        )
        for security_id, bars in etf_bars.items()
    }
    changed = run_etf_rotation_backtest(
        mutated,
        security_ids=identifiers,
        config=config,
    )

    assert changed.rebalances[0] == baseline.rebalances[0]


def test_dual_horizon_requires_shorter_confirmation_window() -> None:
    with pytest.raises(
        ValueError,
        match="confirmation_lookback_bars must be shorter",
    ):
        EtfRotationBacktestConfig(
            signal_model=EtfMomentumSignalModel.DUAL_HORIZON_CONSENSUS,
            confirmation_lookback_bars=252,
        )


def test_skip_recent_month_uses_t_minus_21_as_the_ranking_endpoint(
    etf_bars: dict[str, tuple[Bar, ...]],
) -> None:
    identifiers = tuple(etf_bars)
    security_id = identifiers[0]
    changed_bars = list(etf_bars[security_id])
    initial_close = changed_bars[0].close_price
    for index in range(232, 253):
        changed_bars[index] = changed_bars[index].model_copy(
            update={
                "open_price": initial_close * 0.51,
                "high_price": initial_close * 0.52,
                "low_price": initial_close * 0.49,
                "close_price": initial_close * 0.50,
            }
        )
    candidate_bars = dict(etf_bars)
    candidate_bars[security_id] = tuple(changed_bars)

    baseline = run_etf_rotation_backtest(candidate_bars, security_ids=identifiers)
    skipped = run_etf_rotation_backtest(
        candidate_bars,
        security_ids=identifiers,
        config=EtfRotationBacktestConfig(signal_model=EtfMomentumSignalModel.SKIP_RECENT_MONTH),
    )

    assert security_id not in baseline.rebalances[0].selected_security_ids
    assert security_id in skipped.rebalances[0].selected_security_ids
    assert skipped.rebalances[0].momentum_scores[security_id] == pytest.approx(
        etf_bars[security_id][231].close_price / etf_bars[security_id][0].close_price - 1.0
    )


def test_skip_recent_month_ranking_ignores_the_excluded_21_bars(
    etf_bars: dict[str, tuple[Bar, ...]],
) -> None:
    config = EtfRotationBacktestConfig(signal_model=EtfMomentumSignalModel.SKIP_RECENT_MONTH)
    identifiers = tuple(etf_bars)
    baseline = run_etf_rotation_backtest(
        etf_bars,
        security_ids=identifiers,
        config=config,
    )
    mutated = {
        security_id: tuple(
            bar
            if index <= 231 or index > 252
            else bar.model_copy(
                update={
                    "open_price": bar.open_price * 4,
                    "high_price": bar.high_price * 4,
                    "low_price": bar.low_price * 4,
                    "close_price": bar.close_price * 4,
                }
            )
            for index, bar in enumerate(bars)
        )
        for security_id, bars in etf_bars.items()
    }
    changed = run_etf_rotation_backtest(
        mutated,
        security_ids=identifiers,
        config=config,
    )

    assert (
        changed.rebalances[0].selected_security_ids == baseline.rebalances[0].selected_security_ids
    )
    assert changed.rebalances[0].momentum_scores == baseline.rebalances[0].momentum_scores


def test_skip_recent_month_requires_a_shorter_skip_window() -> None:
    with pytest.raises(
        ValueError,
        match="skip_recent_bars must be shorter",
    ):
        EtfRotationBacktestConfig(
            signal_model=EtfMomentumSignalModel.SKIP_RECENT_MONTH,
            skip_recent_bars=252,
        )


def test_compact_report_identifies_the_research_signal_model(
    etf_bars: dict[str, tuple[Bar, ...]],
) -> None:
    config = EtfRotationBacktestConfig(signal_model=EtfMomentumSignalModel.DUAL_HORIZON_CONSENSUS)
    report = validate_etf_rotation_strategy(
        etf_bars,
        security_ids=tuple(etf_bars),
        config=config,
    )

    compact = _compact_rotation_report(report.model_dump(mode="json"))

    assert compact["signal"] == {
        "model": "DUAL_HORIZON_CONSENSUS",
        "formation_lookback_bars": 252,
        "confirmation_lookback_bars": 126,
        "skip_recent_bars": 21,
    }
    assert compact["exposure"] == {
        "model": "INVERSE_VOLATILITY",
        "volatility_lookback_bars": 63,
        "target_annual_volatility": 0.2,
        "min_position_fraction": 0.25,
        "max_position_fraction": 1.0,
    }


def test_current_allocation_reuses_latest_scheduled_rebalance(
    etf_bars: dict[str, tuple[Bar, ...]],
) -> None:
    security_ids = tuple(etf_bars)
    backtest = run_etf_rotation_backtest(etf_bars, security_ids=security_ids)
    snapshot = build_current_etf_rotation_allocation(
        etf_bars,
        security_ids=security_ids,
    )

    latest_rebalance = backtest.rebalances[-1]
    assert snapshot.as_of_date == backtest.evaluation_end
    assert snapshot.signal_date == latest_rebalance.signal_date
    assert snapshot.execution_date == latest_rebalance.execution_date
    assert snapshot.selected_security_ids == latest_rebalance.selected_security_ids
    assert snapshot.momentum_scores == latest_rebalance.momentum_scores
    assert sum(snapshot.target_weights.values()) == pytest.approx(snapshot.target_position_fraction)
    assert 1 <= snapshot.bars_until_next_rebalance <= 21


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


def test_rebalance_trades_only_weight_delta_and_reconciles_costs(
    etf_bars: dict[str, tuple[Bar, ...]],
) -> None:
    flat_after_signal = {
        security_id: tuple(
            bar
            if index <= 252
            else bar.model_copy(
                update={
                    "open_price": bars[252].close_price,
                    "high_price": bars[252].close_price,
                    "low_price": bars[252].close_price,
                    "close_price": bars[252].close_price,
                }
            )
            for index, bar in enumerate(bars)
        )
        for security_id, bars in etf_bars.items()
    }
    config = EtfRotationBacktestConfig(
        target_annual_volatility=1.0,
        min_position_fraction=1.0,
        max_position_fraction=1.0,
        round_trip_cost_bps=15.0,
    )

    result = run_etf_rotation_backtest(
        flat_after_signal,
        security_ids=tuple(flat_after_signal),
        config=config,
    )

    one_way_cost = config.round_trip_cost_bps / 20_000.0
    expected_final_equity = (1.0 - one_way_cost) / (1.0 + one_way_cost)
    assert result.total_return == pytest.approx(expected_final_equity - 1.0)
    assert result.rebalances[0].turnover_fraction == pytest.approx(1.0 / (1.0 + one_way_cost))
    assert result.rebalances[1].turnover_fraction == pytest.approx(0.0, abs=1e-12)
    assert result.rebalances[1].trade_weight_changes == {}
    assert result.cumulative_turnover == pytest.approx(1.0 + 1.0 / (1.0 + one_way_cost))
    assert result.cumulative_transaction_cost == pytest.approx(
        2.0 * one_way_cost / (1.0 + one_way_cost)
    )


def test_rebalance_event_exposes_target_weights_and_actual_turnover(
    etf_bars: dict[str, tuple[Bar, ...]],
) -> None:
    result = run_etf_rotation_backtest(etf_bars, security_ids=tuple(etf_bars))

    for event in result.rebalances:
        assert set(event.target_weights) == set(event.selected_security_ids)
        assert sum(event.target_weights.values()) == pytest.approx(event.target_position_fraction)
        assert sum(abs(value) for value in event.trade_weight_changes.values()) == pytest.approx(
            event.turnover_fraction
        )
        assert event.transaction_cost_fraction >= 0


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
