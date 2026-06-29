"""ETF medium-term rotation baseline strategy."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

from pydantic import AwareDatetime, Field

from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import NonEmptyString
from china_quant_platform.strategies.base import (
    DriverDirection,
    Explanation,
    ExplanationDriver,
    RawSignal,
    RawSignalIntent,
    StrategyCondition,
    StrategyContext,
    StrategyMetadata,
    WarmupSpec,
)


class ResearchStatus(StrEnum):
    RESEARCH = "RESEARCH"
    VALIDATED = "VALIDATED"
    PAPER_TRADING = "PAPER_TRADING"
    PRODUCTION = "PRODUCTION"


class EtfUniverseMember(DomainModel):
    security_id: NonEmptyString
    name: NonEmptyString
    as_of: AwareDatetime
    approved: bool
    listed: bool
    liquidity_score: float = Field(ge=0, le=1)
    asset_bucket: NonEmptyString


class EtfSignalFeatures(DomainModel):
    momentum: float
    absolute_momentum: float
    trend_strength: float = Field(ge=-1, le=1)
    volatility: float = Field(ge=0)
    average_correlation: float = Field(ge=-1, le=1)


class EtfRotationConfig(DomainModel):
    momentum_weight: float = 0.45
    absolute_momentum_weight: float = 0.25
    trend_weight: float = 0.20
    volatility_weight: float = 0.10
    correlation_penalty_weight: float = 0.10
    min_liquidity_score: float = Field(default=0.5, ge=0, le=1)
    min_absolute_momentum: float = 0.0
    max_volatility: float = Field(default=0.35, ge=0)
    max_average_correlation: float = Field(default=0.90, ge=-1, le=1)
    max_positions: int = Field(default=1, ge=1)
    target_gross_exposure: float = Field(default=0.90, gt=0, le=1)
    cash_weight_when_abstain: float = Field(default=1.0, ge=0, le=1)


class EtfRotationScore(DomainModel):
    security_id: NonEmptyString
    score: float
    target_weight: float = Field(ge=0, le=1)
    cash_weight: float = Field(ge=0, le=1)
    reasons: tuple[NonEmptyString, ...]


class EtfRotationSelection(DomainModel):
    as_of: AwareDatetime
    selected: tuple[EtfRotationScore, ...]
    rejected: dict[str, tuple[NonEmptyString, ...]]
    research_status: ResearchStatus = ResearchStatus.RESEARCH


class CostTurnoverScenario(DomainModel):
    scenario_id: NonEmptyString
    gross_return: float
    turnover: float = Field(ge=0)
    cost_bps: float = Field(ge=0)
    net_return: float


class EtfRotationStrategy:
    strategy_id = "strategy.etf_rotation"
    version = "v1"
    horizon = 20

    def __init__(self, config: EtfRotationConfig | None = None) -> None:
        self._config = config or EtfRotationConfig()

    def metadata(self) -> StrategyMetadata:
        return StrategyMetadata(
            strategy_id=self.strategy_id,
            version=self.version,
            model_version="research.etf_rotation.v1",
            name="ETF medium-term rotation baseline",
            horizon=self.horizon,
            description=(
                "Research baseline using point-in-time ETF momentum, trend, "
                "volatility, and correlation."
            ),
            applicable_conditions=(
                StrategyCondition(
                    name="approved_liquid_etf_pool",
                    description=(
                        "ETF is approved, listed, liquid, and visible at the evaluation time."
                    ),
                ),
            ),
            invalidation_conditions=(
                StrategyCondition(
                    name="momentum_or_liquidity_breaks",
                    description="Absolute momentum, trend, liquidity, or risk constraints fail.",
                ),
            ),
            warmup=self.warmup_requirements(),
        )

    def warmup_requirements(self) -> WarmupSpec:
        return WarmupSpec(
            minimum_bars=60,
            required_factors=(
                "momentum.ret_20d.v1",
                "risk.volatility_20d.v1",
            ),
        )

    def rank_universe(
        self,
        *,
        members: tuple[EtfUniverseMember, ...],
        features: dict[str, EtfSignalFeatures],
    ) -> EtfRotationSelection:
        selected: list[EtfRotationScore] = []
        rejected: dict[str, tuple[NonEmptyString, ...]] = {}
        scored: list[EtfRotationScore] = []
        as_of = members[0].as_of if members else None
        if as_of is None:
            raise ValueError("ETF universe must contain at least one member")

        for member in members:
            reasons = _member_rejection_reasons(
                member, features.get(member.security_id), self._config
            )
            if reasons:
                rejected[member.security_id] = reasons
                continue
            feature = features[member.security_id]
            score = _score_features(feature, self._config)
            scored.append(
                EtfRotationScore(
                    security_id=member.security_id,
                    score=score,
                    target_weight=0.0,
                    cash_weight=0.0,
                    reasons=("selected_by_rotation_score",),
                )
            )

        scored.sort(key=lambda item: (item.score, item.security_id), reverse=True)
        chosen = scored[: self._config.max_positions]
        if chosen:
            target_weight = self._config.target_gross_exposure / len(chosen)
            cash_weight = max(1.0 - self._config.target_gross_exposure, 0.0)
            selected = [
                item.model_copy(update={"target_weight": target_weight, "cash_weight": cash_weight})
                for item in chosen
            ]
        return EtfRotationSelection(
            as_of=as_of,
            selected=tuple(selected),
            rejected=rejected,
        )

    def generate_signal(self, context: StrategyContext) -> RawSignal:
        selected_security_id = str(context.metadata.get("selected_security_id", ""))
        score = float(context.metadata.get("rotation_score", 0.0) or 0.0)
        confidence = min(max(abs(score), 0.0), 1.0)
        is_selected = selected_security_id == context.security_id
        intent = RawSignalIntent.BUY_BIAS if is_selected else RawSignalIntent.WATCH
        if not selected_security_id:
            intent = RawSignalIntent.ABSTAIN

        return RawSignal(
            strategy_id=self.strategy_id,
            strategy_version=self.version,
            security_id=context.security_id,
            generated_at=context.as_of,
            valid_until=context.as_of + timedelta(days=7),
            horizon=self.horizon,
            intent=intent,
            score=score,
            confidence=confidence,
            data_snapshot_id=context.data_snapshot_id,
            model_version="research.etf_rotation.v1",
            applicable_conditions=self.metadata().applicable_conditions,
            invalidation_conditions=self.metadata().invalidation_conditions,
            factor_values=dict(context.factors),
            diagnostics={
                "selected_security_id": selected_security_id,
                "research_status": ResearchStatus.RESEARCH.value,
            },
        )

    def explain(self, context: StrategyContext, signal: RawSignal) -> Explanation:
        return Explanation(
            strategy_id=signal.strategy_id,
            strategy_version=signal.strategy_version,
            security_id=signal.security_id,
            generated_at=signal.generated_at,
            data_snapshot_id=signal.data_snapshot_id,
            summary=(
                "ETF rotation baseline signal; downstream rules and risk gates remain required."
            ),
            drivers=(
                ExplanationDriver(
                    name="rotation_score",
                    value=signal.score,
                    contribution=signal.score,
                    direction=DriverDirection.POSITIVE
                    if signal.score >= 0
                    else DriverDirection.NEGATIVE,
                    description="Combined momentum, trend, volatility, and correlation score.",
                ),
            ),
            applicable_conditions=self.metadata().applicable_conditions,
            invalidation_conditions=self.metadata().invalidation_conditions,
            audit_references=(context.data_snapshot_id, "research.etf_rotation.v1"),
        )


def cost_turnover_sensitivity(
    *,
    gross_return: float,
    turnovers: tuple[float, ...],
    cost_bps_values: tuple[float, ...],
) -> tuple[CostTurnoverScenario, ...]:
    scenarios: list[CostTurnoverScenario] = []
    for turnover in turnovers:
        for cost_bps in cost_bps_values:
            cost_drag = turnover * cost_bps / 10_000.0
            scenarios.append(
                CostTurnoverScenario(
                    scenario_id=f"turnover-{turnover:g}-cost-{cost_bps:g}bps",
                    gross_return=gross_return,
                    turnover=turnover,
                    cost_bps=cost_bps,
                    net_return=gross_return - cost_drag,
                )
            )
    return tuple(scenarios)


def _member_rejection_reasons(
    member: EtfUniverseMember,
    feature: EtfSignalFeatures | None,
    config: EtfRotationConfig,
) -> tuple[NonEmptyString, ...]:
    reasons: list[str] = []
    if not member.approved:
        reasons.append("not_approved")
    if not member.listed:
        reasons.append("not_listed")
    if member.liquidity_score < config.min_liquidity_score:
        reasons.append("liquidity_below_threshold")
    if feature is None:
        reasons.append("missing_features")
        return tuple(reasons)
    if feature.absolute_momentum < config.min_absolute_momentum:
        reasons.append("absolute_momentum_below_threshold")
    if feature.volatility > config.max_volatility:
        reasons.append("volatility_above_threshold")
    if feature.average_correlation > config.max_average_correlation:
        reasons.append("correlation_above_threshold")
    return tuple(reasons)


def _score_features(feature: EtfSignalFeatures, config: EtfRotationConfig) -> float:
    correlation_penalty = max(feature.average_correlation - config.max_average_correlation, 0.0)
    return (
        feature.momentum * config.momentum_weight
        + feature.absolute_momentum * config.absolute_momentum_weight
        + feature.trend_strength * config.trend_weight
        - feature.volatility * config.volatility_weight
        - correlation_penalty * config.correlation_penalty_weight
    )
