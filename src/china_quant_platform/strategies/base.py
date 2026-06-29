"""Strategy interfaces, raw signals, and explanation contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Protocol, Self, runtime_checkable

from pydantic import AwareDatetime, Field, model_validator

from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.errors import InsufficientHistory
from china_quant_platform.domain.identifiers import (
    DataSnapshotId,
    ModelVersion,
    NonEmptyString,
    RuleVersion,
    SecurityId,
    StrategyId,
)

type StrategyScalar = str | int | float | bool | None

FORBIDDEN_RAW_SIGNAL_KEYS = frozenset(
    {
        "account_id",
        "final_signal",
        "limit_price",
        "order_id",
        "order_type",
        "price",
        "quantity",
        "side",
        "target_position",
        "target_weight",
    }
)


class RawSignalIntent(StrEnum):
    BUY_BIAS = "BUY_BIAS"
    ADD_BIAS = "ADD_BIAS"
    HOLD_BIAS = "HOLD_BIAS"
    REDUCE_BIAS = "REDUCE_BIAS"
    SELL_BIAS = "SELL_BIAS"
    WATCH = "WATCH"
    ABSTAIN = "ABSTAIN"


class DriverDirection(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


class StrategyCondition(DomainModel):
    name: NonEmptyString
    description: NonEmptyString
    is_satisfied: bool | None = None


class ExplanationDriver(DomainModel):
    name: NonEmptyString
    value: float | None = None
    contribution: float | None = None
    direction: DriverDirection
    description: NonEmptyString


class WarmupSpec(DomainModel):
    minimum_bars: int = Field(ge=0)
    required_indicators: tuple[NonEmptyString, ...] = ()
    required_factors: tuple[NonEmptyString, ...] = ()

    def missing_requirements(self, context: StrategyContext) -> tuple[str, ...]:
        missing: list[str] = []
        if context.available_bars < self.minimum_bars:
            missing.append(f"bars:{context.available_bars}/{self.minimum_bars}")

        indicator_names = frozenset(context.indicators)
        for name in self.required_indicators:
            if name not in indicator_names:
                missing.append(f"indicator:{name}")

        factor_names = frozenset(context.factors)
        for name in self.required_factors:
            if name not in factor_names:
                missing.append(f"factor:{name}")

        return tuple(missing)


class StrategyMetadata(DomainModel):
    strategy_id: StrategyId
    version: NonEmptyString
    model_version: ModelVersion
    name: NonEmptyString
    horizon: int = Field(ge=1)
    description: NonEmptyString
    applicable_conditions: tuple[StrategyCondition, ...]
    invalidation_conditions: tuple[StrategyCondition, ...]
    warmup: WarmupSpec

    @model_validator(mode="after")
    def require_visible_conditions(self) -> Self:
        if not self.applicable_conditions:
            raise ValueError("strategy metadata must list applicable conditions")
        if not self.invalidation_conditions:
            raise ValueError("strategy metadata must list invalidation conditions")
        return self


class StrategyContext(DomainModel):
    security_id: SecurityId
    as_of: AwareDatetime
    data_snapshot_id: DataSnapshotId
    rule_version: RuleVersion
    available_bars: int = Field(ge=0)
    indicators: dict[str, float] = Field(default_factory=dict)
    factors: dict[str, float] = Field(default_factory=dict)
    market_regime: NonEmptyString = "UNKNOWN"
    metadata: dict[str, StrategyScalar] = Field(default_factory=dict)


class RawSignal(DomainModel):
    strategy_id: StrategyId
    strategy_version: NonEmptyString
    security_id: SecurityId
    generated_at: AwareDatetime
    valid_until: AwareDatetime
    horizon: int = Field(ge=1)
    intent: RawSignalIntent
    score: float = Field(ge=-1, le=1)
    confidence: float = Field(ge=0, le=1)
    data_snapshot_id: DataSnapshotId
    model_version: ModelVersion
    applicable_conditions: tuple[StrategyCondition, ...]
    invalidation_conditions: tuple[StrategyCondition, ...]
    factor_values: dict[str, float] = Field(default_factory=dict)
    diagnostics: dict[str, StrategyScalar] = Field(default_factory=dict)
    requires_data_quality_gate: Literal[True] = True
    requires_rule_gate: Literal[True] = True
    requires_risk_gate: Literal[True] = True

    @model_validator(mode="after")
    def enforce_raw_signal_boundary(self) -> Self:
        if self.valid_until <= self.generated_at:
            raise ValueError("valid_until must be later than generated_at")
        if not self.invalidation_conditions:
            raise ValueError("raw signals must include invalidation conditions")
        forbidden = FORBIDDEN_RAW_SIGNAL_KEYS.intersection(
            {key.lower() for key in self.diagnostics}
        )
        if forbidden:
            keys = ", ".join(sorted(forbidden))
            raise ValueError(f"raw signal diagnostics cannot contain order/final fields: {keys}")
        return self


class Explanation(DomainModel):
    strategy_id: StrategyId
    strategy_version: NonEmptyString
    security_id: SecurityId
    generated_at: AwareDatetime
    data_snapshot_id: DataSnapshotId
    summary: NonEmptyString
    drivers: tuple[ExplanationDriver, ...]
    applicable_conditions: tuple[StrategyCondition, ...]
    invalidation_conditions: tuple[StrategyCondition, ...]
    audit_references: tuple[NonEmptyString, ...] = ()

    @model_validator(mode="after")
    def require_explainable_signal(self) -> Self:
        if not self.drivers:
            raise ValueError("explanations must include at least one driver")
        if not self.applicable_conditions:
            raise ValueError("explanations must include applicable conditions")
        if not self.invalidation_conditions:
            raise ValueError("explanations must include invalidation conditions")
        return self


class StrategyEvaluation(DomainModel):
    signal: RawSignal
    explanation: Explanation

    @model_validator(mode="after")
    def signal_and_explanation_must_match(self) -> Self:
        if self.signal.strategy_id != self.explanation.strategy_id:
            raise ValueError("signal and explanation strategy_id must match")
        if self.signal.strategy_version != self.explanation.strategy_version:
            raise ValueError("signal and explanation strategy_version must match")
        if self.signal.security_id != self.explanation.security_id:
            raise ValueError("signal and explanation security_id must match")
        if self.signal.data_snapshot_id != self.explanation.data_snapshot_id:
            raise ValueError("signal and explanation data_snapshot_id must match")
        if self.explanation.generated_at < self.signal.generated_at:
            raise ValueError("explanation cannot be generated before the signal")
        return self


@runtime_checkable
class Strategy(Protocol):
    strategy_id: str
    version: str
    horizon: int

    def warmup_requirements(self) -> WarmupSpec: ...

    def generate_signal(self, context: StrategyContext) -> RawSignal: ...

    def explain(self, context: StrategyContext, signal: RawSignal) -> Explanation: ...


def evaluate_strategy(strategy: Strategy, context: StrategyContext) -> StrategyEvaluation:
    warmup = strategy.warmup_requirements()
    missing = warmup.missing_requirements(context)
    if missing:
        raise InsufficientHistory(f"strategy warmup requirements are missing: {missing}")

    signal = strategy.generate_signal(context)
    _validate_strategy_signal_identity(strategy, context, signal)
    explanation = strategy.explain(context, signal)
    return StrategyEvaluation(signal=signal, explanation=explanation)


def _validate_strategy_signal_identity(
    strategy: Strategy,
    context: StrategyContext,
    signal: RawSignal,
) -> None:
    if signal.strategy_id != strategy.strategy_id:
        raise ValueError("strategy generated a signal with a mismatched strategy_id")
    if signal.strategy_version != strategy.version:
        raise ValueError("strategy generated a signal with a mismatched version")
    if signal.horizon != strategy.horizon:
        raise ValueError("strategy generated a signal with a mismatched horizon")
    if signal.security_id != context.security_id:
        raise ValueError("strategy generated a signal for a different security")
    if signal.data_snapshot_id != context.data_snapshot_id:
        raise ValueError("strategy generated a signal for a different data snapshot")
