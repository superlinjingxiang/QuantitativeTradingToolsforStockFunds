"""A-share multi-factor trend baseline strategy."""

from __future__ import annotations

from datetime import timedelta

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
from china_quant_platform.strategies.etf_rotation import ResearchStatus


class AShareUniverseMember(DomainModel):
    security_id: NonEmptyString
    as_of: AwareDatetime
    industry: NonEmptyString
    point_in_time_member: bool
    eligible: bool
    listed: bool
    suspended: bool = False
    liquidity_score: float = Field(ge=0, le=1)


class AShareFactorSnapshot(DomainModel):
    visible_at: AwareDatetime
    value: float
    quality: float
    profitability: float
    investment: float
    momentum: float
    relative_strength: float
    low_volatility: float
    liquidity: float
    trend_strength: float = Field(ge=-1, le=1)
    market_state_score: float = Field(ge=-1, le=1)


class AShareTrendConfig(DomainModel):
    value_weight: float = 0.10
    quality_weight: float = 0.15
    profitability_weight: float = 0.10
    investment_weight: float = 0.05
    momentum_weight: float = 0.20
    relative_strength_weight: float = 0.15
    low_volatility_weight: float = 0.10
    liquidity_weight: float = 0.05
    trend_weight: float = 0.10
    min_liquidity_score: float = Field(default=0.5, ge=0, le=1)
    min_trend_strength: float = -0.1
    min_market_state_score: float = -0.2
    max_positions: int = Field(default=5, ge=1)
    target_gross_exposure: float = Field(default=0.80, gt=0, le=1)
    stop_loss: float = Field(default=0.08, ge=0, le=1)
    max_position_drawdown: float = Field(default=0.12, ge=0, le=1)
    exit_trend_threshold: float = -0.2


class AShareTrendScore(DomainModel):
    security_id: NonEmptyString
    industry: NonEmptyString
    score: float
    target_weight: float = Field(ge=0, le=1)
    reasons: tuple[NonEmptyString, ...]


class AShareTrendSelection(DomainModel):
    as_of: AwareDatetime
    selected: tuple[AShareTrendScore, ...]
    rejected: dict[str, tuple[NonEmptyString, ...]]
    research_status: ResearchStatus = ResearchStatus.RESEARCH


class ExitDecision(DomainModel):
    intent: RawSignalIntent
    reasons: tuple[NonEmptyString, ...]


class BreakdownRow(DomainModel):
    group: NonEmptyString
    sample_count: int = Field(ge=0)
    mean_return: float
    hit_rate: float = Field(ge=0, le=1)


class AShareTrendStrategy:
    strategy_id = "strategy.a_share_multi_factor_trend"
    version = "v1"
    horizon = 10

    def __init__(self, config: AShareTrendConfig | None = None) -> None:
        self._config = config or AShareTrendConfig()

    def metadata(self) -> StrategyMetadata:
        return StrategyMetadata(
            strategy_id=self.strategy_id,
            version=self.version,
            model_version="research.a_share_trend.v1",
            name="A-share multi-factor trend baseline",
            horizon=self.horizon,
            description="Research baseline using point-in-time factors and trend confirmation.",
            applicable_conditions=(
                StrategyCondition(
                    name="eligible_point_in_time_a_share_pool",
                    description="Stock is a listed, liquid, point-in-time eligible A-share.",
                ),
            ),
            invalidation_conditions=(
                StrategyCondition(
                    name="exit_or_risk_condition_triggers",
                    description="Trend, drawdown, liquidity, market, or risk condition fails.",
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
        members: tuple[AShareUniverseMember, ...],
        factors: dict[str, AShareFactorSnapshot],
    ) -> AShareTrendSelection:
        if not members:
            raise ValueError("A-share universe must contain at least one member")
        rejected: dict[str, tuple[NonEmptyString, ...]] = {}
        scored: list[AShareTrendScore] = []
        as_of = members[0].as_of

        for member in members:
            snapshot = factors.get(member.security_id)
            reasons = _rejection_reasons(member, snapshot, self._config)
            if reasons:
                rejected[member.security_id] = reasons
                continue
            assert snapshot is not None
            score = _score_snapshot(snapshot, self._config)
            scored.append(
                AShareTrendScore(
                    security_id=member.security_id,
                    industry=member.industry,
                    score=score,
                    target_weight=0.0,
                    reasons=("selected_by_multifactor_trend_score",),
                )
            )

        scored.sort(key=lambda item: (item.score, item.security_id), reverse=True)
        chosen = scored[: self._config.max_positions]
        target_weight = self._config.target_gross_exposure / len(chosen) if chosen else 0.0
        selected = tuple(
            item.model_copy(update={"target_weight": target_weight}) for item in chosen
        )
        return AShareTrendSelection(as_of=as_of, selected=selected, rejected=rejected)

    def evaluate_exit(
        self,
        *,
        holding_return: float,
        position_drawdown: float,
        trend_strength: float,
    ) -> ExitDecision:
        reasons: list[str] = []
        if holding_return <= -self._config.stop_loss:
            reasons.append("stop_loss_triggered")
        if position_drawdown <= -self._config.max_position_drawdown:
            reasons.append("position_drawdown_triggered")
        if trend_strength < self._config.exit_trend_threshold:
            reasons.append("trend_break_triggered")
        return ExitDecision(
            intent=RawSignalIntent.SELL_BIAS if reasons else RawSignalIntent.HOLD_BIAS,
            reasons=tuple(reasons),
        )

    def generate_signal(self, context: StrategyContext) -> RawSignal:
        selected_security_id = str(context.metadata.get("selected_security_id", ""))
        score = float(context.metadata.get("trend_score", 0.0) or 0.0)
        intent = (
            RawSignalIntent.BUY_BIAS
            if selected_security_id == context.security_id
            else RawSignalIntent.WATCH
        )
        if not selected_security_id:
            intent = RawSignalIntent.ABSTAIN
        return RawSignal(
            strategy_id=self.strategy_id,
            strategy_version=self.version,
            security_id=context.security_id,
            generated_at=context.as_of,
            valid_until=context.as_of + timedelta(days=self.horizon),
            horizon=self.horizon,
            intent=intent,
            score=max(min(score, 1.0), -1.0),
            confidence=min(max(abs(score), 0.0), 1.0),
            data_snapshot_id=context.data_snapshot_id,
            model_version="research.a_share_trend.v1",
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
            summary="A-share multi-factor trend baseline signal requires downstream risk gates.",
            drivers=(
                ExplanationDriver(
                    name="trend_score",
                    value=signal.score,
                    contribution=signal.score,
                    direction=DriverDirection.POSITIVE
                    if signal.score >= 0
                    else DriverDirection.NEGATIVE,
                    description="Combined point-in-time multi-factor and trend score.",
                ),
            ),
            applicable_conditions=self.metadata().applicable_conditions,
            invalidation_conditions=self.metadata().invalidation_conditions,
            audit_references=(context.data_snapshot_id, "research.a_share_trend.v1"),
        )


def cross_sectional_percentile_ranks(
    values: dict[str, float],
    *,
    higher_is_better: bool = True,
) -> dict[str, float]:
    if not values:
        return {}
    sorted_items = sorted(values.items(), key=lambda item: (item[1], item[0]))
    denominator = max(len(sorted_items) - 1, 1)
    ranks = {
        security_id: index / denominator for index, (security_id, _value) in enumerate(sorted_items)
    }
    if higher_is_better:
        return ranks
    return {security_id: 1.0 - rank for security_id, rank in ranks.items()}


def summarize_group_returns(
    group_returns: dict[str, tuple[float, ...]],
) -> tuple[BreakdownRow, ...]:
    rows: list[BreakdownRow] = []
    for group, returns in sorted(group_returns.items()):
        sample_count = len(returns)
        mean_return = 0.0 if sample_count == 0 else sum(returns) / sample_count
        hit_rate = (
            0.0 if sample_count == 0 else sum(1 for value in returns if value > 0) / sample_count
        )
        rows.append(
            BreakdownRow(
                group=group,
                sample_count=sample_count,
                mean_return=mean_return,
                hit_rate=hit_rate,
            )
        )
    return tuple(rows)


def _rejection_reasons(
    member: AShareUniverseMember,
    snapshot: AShareFactorSnapshot | None,
    config: AShareTrendConfig,
) -> tuple[NonEmptyString, ...]:
    reasons: list[str] = []
    if not member.point_in_time_member:
        reasons.append("not_in_point_in_time_universe")
    if not member.eligible:
        reasons.append("not_eligible")
    if not member.listed:
        reasons.append("not_listed")
    if member.suspended:
        reasons.append("suspended")
    if member.liquidity_score < config.min_liquidity_score:
        reasons.append("liquidity_below_threshold")
    if snapshot is None:
        reasons.append("missing_factors")
        return tuple(reasons)
    if snapshot.visible_at > member.as_of:
        reasons.append("factor_not_visible_at_as_of")
    if snapshot.market_state_score < config.min_market_state_score:
        reasons.append("market_state_filter_failed")
    if snapshot.trend_strength < config.min_trend_strength:
        reasons.append("trend_confirmation_failed")
    return tuple(reasons)


def _score_snapshot(snapshot: AShareFactorSnapshot, config: AShareTrendConfig) -> float:
    return (
        snapshot.value * config.value_weight
        + snapshot.quality * config.quality_weight
        + snapshot.profitability * config.profitability_weight
        + snapshot.investment * config.investment_weight
        + snapshot.momentum * config.momentum_weight
        + snapshot.relative_strength * config.relative_strength_weight
        + snapshot.low_volatility * config.low_volatility_weight
        + snapshot.liquidity * config.liquidity_weight
        + snapshot.trend_strength * config.trend_weight
    )
