"""Strategy protocol and raw signal boundary tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from china_quant_platform.domain import InsufficientHistory
from china_quant_platform.strategies import (
    DriverDirection,
    Explanation,
    ExplanationDriver,
    RawSignal,
    RawSignalIntent,
    StrategyCondition,
    StrategyContext,
    StrategyEvaluation,
    StrategyMetadata,
    WarmupSpec,
    evaluate_strategy,
)


def as_of() -> datetime:
    return datetime(2026, 1, 5, 15, 0, tzinfo=UTC)


def condition(name: str = "trend_available") -> StrategyCondition:
    return StrategyCondition(
        name=name,
        description=f"{name} condition is visible to the user.",
        is_satisfied=True,
    )


def context(*, available_bars: int = 30) -> StrategyContext:
    return StrategyContext(
        security_id="SSE:600519",
        as_of=as_of(),
        data_snapshot_id="snapshot-001",
        rule_version="rules-cn-v1",
        available_bars=available_bars,
        indicators={"technical.sma.v1": 101.0},
        factors={"momentum.ret_20d.v1": 0.08},
        market_regime="NORMAL",
    )


def raw_signal_payload() -> dict[str, Any]:
    current_time = as_of()
    common_condition = condition()
    return {
        "strategy_id": "strategy.demo",
        "strategy_version": "v1",
        "security_id": "SSE:600519",
        "generated_at": current_time,
        "valid_until": current_time + timedelta(days=1),
        "horizon": 5,
        "intent": RawSignalIntent.BUY_BIAS,
        "score": 0.42,
        "confidence": 0.7,
        "data_snapshot_id": "snapshot-001",
        "model_version": "model-demo-v1",
        "applicable_conditions": (common_condition,),
        "invalidation_conditions": (condition("trend_breaks"),),
        "factor_values": {"momentum.ret_20d.v1": 0.08},
        "diagnostics": {"rank": 3},
    }


def explanation(signal: RawSignal) -> Explanation:
    return Explanation(
        strategy_id=signal.strategy_id,
        strategy_version=signal.strategy_version,
        security_id=signal.security_id,
        generated_at=signal.generated_at,
        data_snapshot_id=signal.data_snapshot_id,
        summary="Momentum is positive but still requires downstream gates.",
        drivers=(
            ExplanationDriver(
                name="momentum.ret_20d.v1",
                value=0.08,
                contribution=0.42,
                direction=DriverDirection.POSITIVE,
                description="20 day return contributes positively.",
            ),
        ),
        applicable_conditions=signal.applicable_conditions,
        invalidation_conditions=signal.invalidation_conditions,
        audit_references=("snapshot-001", "model-demo-v1"),
    )


class DemoStrategy:
    strategy_id = "strategy.demo"
    version = "v1"
    horizon = 5

    def warmup_requirements(self) -> WarmupSpec:
        return WarmupSpec(
            minimum_bars=21,
            required_indicators=("technical.sma.v1",),
            required_factors=("momentum.ret_20d.v1",),
        )

    def generate_signal(self, strategy_context: StrategyContext) -> RawSignal:
        payload = raw_signal_payload()
        payload["security_id"] = strategy_context.security_id
        payload["generated_at"] = strategy_context.as_of
        payload["valid_until"] = strategy_context.as_of + timedelta(days=1)
        payload["data_snapshot_id"] = strategy_context.data_snapshot_id
        return RawSignal.model_validate(payload)

    def explain(self, strategy_context: StrategyContext, signal: RawSignal) -> Explanation:
        assert strategy_context.security_id == signal.security_id
        return explanation(signal)


def test_raw_signal_rejects_order_fields_and_gate_bypass() -> None:
    with pytest.raises(ValidationError):
        RawSignal.model_validate(raw_signal_payload() | {"target_position": 0.5})

    with pytest.raises(ValidationError):
        RawSignal.model_validate(raw_signal_payload() | {"diagnostics": {"target_weight": 0.5}})

    with pytest.raises(ValidationError):
        RawSignal.model_validate(raw_signal_payload() | {"requires_rule_gate": False})


def test_strategy_metadata_requires_visible_conditions() -> None:
    metadata = StrategyMetadata(
        strategy_id="strategy.demo",
        version="v1",
        model_version="model-demo-v1",
        name="Demo momentum strategy",
        horizon=5,
        description="A test strategy that emits raw bias only.",
        applicable_conditions=(condition(),),
        invalidation_conditions=(condition("trend_breaks"),),
        warmup=WarmupSpec(minimum_bars=21),
    )

    assert metadata.name == "Demo momentum strategy"

    with pytest.raises(ValidationError):
        StrategyMetadata(
            strategy_id="strategy.demo",
            version="v1",
            model_version="model-demo-v1",
            name="Demo momentum strategy",
            horizon=5,
            description="Missing conditions should fail.",
            applicable_conditions=(),
            invalidation_conditions=(condition("trend_breaks"),),
            warmup=WarmupSpec(minimum_bars=21),
        )


def test_warmup_spec_blocks_strategy_evaluation_when_history_is_missing() -> None:
    with pytest.raises(InsufficientHistory):
        evaluate_strategy(DemoStrategy(), context(available_bars=20))


def test_evaluate_strategy_returns_raw_signal_and_explanation() -> None:
    evaluation = evaluate_strategy(DemoStrategy(), context())

    assert evaluation.signal.intent is RawSignalIntent.BUY_BIAS
    assert evaluation.signal.requires_data_quality_gate is True
    assert evaluation.signal.requires_rule_gate is True
    assert evaluation.signal.requires_risk_gate is True
    assert evaluation.explanation.summary.startswith("Momentum is positive")
    assert evaluation.explanation.audit_references == ("snapshot-001", "model-demo-v1")


def test_strategy_identity_and_explanation_must_match() -> None:
    strategy = DemoStrategy()
    payload = raw_signal_payload()
    payload["strategy_id"] = "strategy.other"
    bad_signal = RawSignal.model_validate(payload)

    with pytest.raises(ValueError):
        StrategyEvaluation(
            signal=bad_signal,
            explanation=explanation(RawSignal.model_validate(raw_signal_payload())),
        )

    class MismatchedSignalStrategy(DemoStrategy):
        def generate_signal(self, strategy_context: StrategyContext) -> RawSignal:
            payload = raw_signal_payload()
            payload["strategy_id"] = "strategy.other"
            payload["generated_at"] = strategy_context.as_of
            payload["valid_until"] = strategy_context.as_of + timedelta(days=1)
            return RawSignal.model_validate(payload)

    with pytest.raises(ValueError):
        evaluate_strategy(MismatchedSignalStrategy(), context())

    assert strategy.strategy_id == "strategy.demo"
