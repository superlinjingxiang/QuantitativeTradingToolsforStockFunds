"""Analysis report assembly tests."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from china_quant_platform.analysis import build_analysis_report
from china_quant_platform.domain import (
    AbstainReason,
    DataHealth,
    DataHealthStatus,
    FinalSignal,
)
from china_quant_platform.forecasting import ForecastConfig, ForecastEngine, ForecastResult
from china_quant_platform.risk import RiskCheckResult
from china_quant_platform.strategies import (
    DriverDirection,
    Explanation,
    ExplanationDriver,
    RawSignal,
    RawSignalIntent,
    StrategyCondition,
    StrategyEvaluation,
)


def as_of() -> datetime:
    return datetime(2026, 6, 29, 15, 0, tzinfo=UTC)


def condition(name: str) -> StrategyCondition:
    return StrategyCondition(
        name=name,
        description=f"{name} is visible before the report is shown.",
        is_satisfied=True,
    )


def healthy_data() -> DataHealth:
    return DataHealth(status=DataHealthStatus.HEALTHY, block_signal=False, as_of=as_of())


def stale_data() -> DataHealth:
    return DataHealth(
        status=DataHealthStatus.STALE,
        block_signal=True,
        as_of=as_of(),
        issues=("stale quote",),
    )


def evaluation(intent: RawSignalIntent = RawSignalIntent.BUY_BIAS) -> StrategyEvaluation:
    current_time = as_of()
    signal = RawSignal(
        strategy_id="strategy.demo",
        strategy_version="v1",
        security_id="SSE:600519",
        generated_at=current_time,
        valid_until=current_time + timedelta(days=1),
        horizon=5,
        intent=intent,
        score=0.52,
        confidence=0.72,
        data_snapshot_id="snapshot-020",
        model_version="strategy-model-v1",
        applicable_conditions=(condition("trend_confirmed"),),
        invalidation_conditions=(condition("trend_breaks"),),
        factor_values={"momentum.ret_20d.v1": 0.08},
        diagnostics={"rank": 2},
    )
    explanation = Explanation(
        strategy_id=signal.strategy_id,
        strategy_version=signal.strategy_version,
        security_id=signal.security_id,
        generated_at=signal.generated_at,
        data_snapshot_id=signal.data_snapshot_id,
        summary="Momentum is constructive but still requires gates.",
        drivers=(
            ExplanationDriver(
                name="momentum.ret_20d.v1",
                value=0.08,
                contribution=0.52,
                direction=DriverDirection.POSITIVE,
                description="Momentum supports the candidate.",
            ),
            ExplanationDriver(
                name="risk.volatility_20d.v1",
                value=0.18,
                contribution=-0.2,
                direction=DriverDirection.NEGATIVE,
                description="Volatility reduces conviction.",
            ),
        ),
        applicable_conditions=signal.applicable_conditions,
        invalidation_conditions=signal.invalidation_conditions,
        audit_references=("snapshot-020", "strategy-model-v1"),
    )
    return StrategyEvaluation(signal=signal, explanation=explanation)


def ready_forecast() -> ForecastResult:
    engine = ForecastEngine(
        config=ForecastConfig(
            horizon=5,
            model_version="forecast-model-v1",
            min_samples=3,
            min_direction_confidence=0.4,
        )
    )
    return engine.predict(
        raw_score=0.8,
        sample_count=120,
        ood_score=0.1,
        drift_score=0.1,
        return_samples=(-0.02, 0.01, 0.03, 0.05, 0.09),
    )


def ood_forecast() -> ForecastResult:
    engine = ForecastEngine(
        config=ForecastConfig(
            horizon=5,
            model_version="forecast-model-v1",
            min_samples=3,
            max_ood_score=0.2,
            min_direction_confidence=0.4,
        )
    )
    return engine.predict(
        raw_score=0.8,
        sample_count=120,
        ood_score=0.9,
        drift_score=0.1,
        return_samples=(-0.04, -0.01, 0.02, 0.04, 0.06),
    )


def test_report_builder_emits_tradeable_analysis_report_with_audit_fields() -> None:
    report = build_analysis_report(
        evaluation=evaluation(),
        forecast=ready_forecast(),
        data_health=healthy_data(),
        market_regime="RANGE_STRONG",
        rule_version="rules-cn-v1",
        risk_result=RiskCheckResult(
            allowed=True,
            target_position_limit=0.05,
            projected_weight=0.04,
            projected_total_exposure=0.40,
        ),
    )

    assert report.final_signal is FinalSignal.BUY_CANDIDATE
    assert report.abstain_reason is None
    assert report.strategy_id == "strategy.demo"
    assert report.model_version == "forecast-model-v1"
    assert report.rule_version == "rules-cn-v1"
    assert report.data_snapshot_id == "snapshot-020"
    assert report.target_position_limit == 0.05
    assert math.isclose(
        report.direction_probabilities.up
        + report.direction_probabilities.flat
        + report.direction_probabilities.down,
        1.0,
    )
    assert report.expected_return_quantiles["p50"] == 0.03
    assert report.positive_drivers
    assert report.negative_drivers
    assert report.exit_or_invalidation_conditions


def test_report_builder_converts_stale_data_to_abstain_report() -> None:
    report = build_analysis_report(
        evaluation=evaluation(),
        forecast=ready_forecast(),
        data_health=stale_data(),
        market_regime="RANGE_STRONG",
        rule_version="rules-cn-v1",
    )

    assert report.final_signal is FinalSignal.ABSTAIN
    assert report.abstain_reason is AbstainReason.DATA
    assert report.data_health.block_signal is True
    assert any("stale quote" in driver for driver in report.negative_drivers)


def test_report_builder_converts_ood_forecast_to_model_abstain() -> None:
    report = build_analysis_report(
        evaluation=evaluation(),
        forecast=ood_forecast(),
        data_health=healthy_data(),
        market_regime="RANGE_STRONG",
        rule_version="rules-cn-v1",
    )

    assert report.final_signal is FinalSignal.ABSTAIN
    assert report.abstain_reason is AbstainReason.MODEL_UNCERTAINTY
    assert report.direction_probabilities.up > report.direction_probabilities.down
    assert report.expected_return_quantiles["p05"] < report.expected_return_quantiles["p95"]
    assert any("OUT_OF_DISTRIBUTION" in driver for driver in report.negative_drivers)
