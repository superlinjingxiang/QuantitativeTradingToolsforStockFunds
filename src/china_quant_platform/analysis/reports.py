"""Build user-visible analysis reports from strategy, forecast, and gates."""

from __future__ import annotations

from china_quant_platform.domain import (
    AbstainReason,
    AnalysisReport,
    DataHealth,
    DirectionProbabilities,
    FinalSignal,
)
from china_quant_platform.domain.identifiers import NonEmptyString, RuleVersion
from china_quant_platform.forecasting import AbstainTrigger, ForecastResult, ForecastStatus
from china_quant_platform.risk import RiskCheckResult
from china_quant_platform.strategies import (
    DriverDirection,
    ExplanationDriver,
    RawSignalIntent,
    StrategyCondition,
    StrategyEvaluation,
)

INTENT_TO_FINAL_SIGNAL: dict[RawSignalIntent, FinalSignal] = {
    RawSignalIntent.BUY_BIAS: FinalSignal.BUY_CANDIDATE,
    RawSignalIntent.ADD_BIAS: FinalSignal.ADD_CANDIDATE,
    RawSignalIntent.HOLD_BIAS: FinalSignal.HOLD,
    RawSignalIntent.REDUCE_BIAS: FinalSignal.REDUCE,
    RawSignalIntent.SELL_BIAS: FinalSignal.SELL,
    RawSignalIntent.WATCH: FinalSignal.WATCH,
    RawSignalIntent.ABSTAIN: FinalSignal.ABSTAIN,
}


def build_analysis_report(
    *,
    evaluation: StrategyEvaluation,
    forecast: ForecastResult,
    data_health: DataHealth,
    market_regime: NonEmptyString,
    rule_version: RuleVersion,
    risk_result: RiskCheckResult | None = None,
    rule_reasons: tuple[NonEmptyString, ...] = (),
    grade: NonEmptyString | None = None,
    target_position_limit: float | None = None,
) -> AnalysisReport:
    """Combine raw strategy output, forecast, and gates into AnalysisReport."""

    probabilities = forecast.direction_probabilities
    if probabilities is None:
        raise ValueError("analysis reports require forecast direction probabilities")

    signal = evaluation.signal
    explanation = evaluation.explanation
    final_signal, abstain_reason = _final_signal_and_reason(
        intent=signal.intent,
        data_health=data_health,
        forecast=forecast,
        risk_result=risk_result,
        rule_reasons=rule_reasons,
    )
    positive_drivers = _driver_labels(explanation.drivers, DriverDirection.POSITIVE)
    negative_drivers = _negative_drivers(
        explanation.drivers,
        data_health=data_health,
        forecast=forecast,
        risk_result=risk_result,
        rule_reasons=rule_reasons,
    )
    exit_conditions = _condition_labels(signal.invalidation_conditions)
    if final_signal is FinalSignal.ABSTAIN and not exit_conditions:
        exit_conditions = ("No trade until the blocking reason is resolved.",)

    position_limit = target_position_limit
    if position_limit is None and risk_result is not None:
        position_limit = risk_result.target_position_limit

    return AnalysisReport(
        security_id=signal.security_id,
        as_of=signal.generated_at,
        data_health=data_health,
        strategy_id=signal.strategy_id,
        strategy_version=signal.strategy_version,
        horizon=forecast.horizon,
        market_regime=market_regime,
        direction_probabilities=_normalize_probabilities(probabilities),
        raw_signal=signal.intent.value,
        final_signal=final_signal,
        valid_until=signal.valid_until,
        positive_drivers=positive_drivers,
        negative_drivers=negative_drivers,
        model_version=forecast.model_version,
        rule_version=rule_version,
        data_snapshot_id=signal.data_snapshot_id,
        expected_return_quantiles=forecast.expected_return_quantiles,
        expected_drawdown=forecast.expected_drawdown,
        grade=grade or _grade_for_signal(signal.confidence, probabilities, final_signal),
        target_position_limit=position_limit,
        exit_or_invalidation_conditions=exit_conditions,
        abstain_reason=abstain_reason,
    )


def _final_signal_and_reason(
    *,
    intent: RawSignalIntent,
    data_health: DataHealth,
    forecast: ForecastResult,
    risk_result: RiskCheckResult | None,
    rule_reasons: tuple[NonEmptyString, ...],
) -> tuple[FinalSignal, AbstainReason | None]:
    if data_health.block_signal:
        return FinalSignal.ABSTAIN, AbstainReason.DATA
    if rule_reasons:
        return FinalSignal.ABSTAIN, AbstainReason.RULE
    if forecast.status is ForecastStatus.ABSTAIN:
        return FinalSignal.ABSTAIN, _forecast_abstain_reason(forecast)
    if risk_result is not None and not risk_result.allowed:
        return FinalSignal.ABSTAIN, _risk_abstain_reason(risk_result)
    if intent is RawSignalIntent.ABSTAIN:
        return FinalSignal.ABSTAIN, AbstainReason.EXPECTED_VALUE
    return INTENT_TO_FINAL_SIGNAL[intent], None


def _forecast_abstain_reason(forecast: ForecastResult) -> AbstainReason:
    if AbstainTrigger.INSUFFICIENT_HISTORY in forecast.abstain_reasons:
        return AbstainReason.INSUFFICIENT_HISTORY
    return AbstainReason.MODEL_UNCERTAINTY


def _risk_abstain_reason(risk_result: RiskCheckResult) -> AbstainReason:
    if any("liquidity" in reason.lower() for reason in risk_result.reasons):
        return AbstainReason.LIQUIDITY
    return AbstainReason.RISK_BUDGET


def _driver_labels(
    drivers: tuple[ExplanationDriver, ...],
    direction: DriverDirection,
) -> tuple[NonEmptyString, ...]:
    labels = tuple(_driver_label(driver) for driver in drivers if driver.direction is direction)
    if labels:
        return labels
    if direction is DriverDirection.POSITIVE:
        return ("No positive driver is strong enough to override downstream gates.",)
    return ("Residual model, execution, and market risk remains.",)


def _negative_drivers(
    drivers: tuple[ExplanationDriver, ...],
    *,
    data_health: DataHealth,
    forecast: ForecastResult,
    risk_result: RiskCheckResult | None,
    rule_reasons: tuple[NonEmptyString, ...],
) -> tuple[NonEmptyString, ...]:
    values = list(_driver_labels(drivers, DriverDirection.NEGATIVE))
    if data_health.block_signal:
        issues = "; ".join(data_health.issues) or "data gate blocks new signals"
        values.append(f"Data health {data_health.status.value}: {issues}")
    if forecast.status is ForecastStatus.ABSTAIN:
        reasons = ", ".join(reason.value for reason in forecast.abstain_reasons)
        values.append(f"Forecast abstains: {reasons}")
    values.extend(rule_reasons)
    if risk_result is not None and not risk_result.allowed:
        values.extend(risk_result.reasons)
    return tuple(values)


def _driver_label(driver: ExplanationDriver) -> str:
    if driver.value is None:
        return f"{driver.name}: {driver.description}"
    return f"{driver.name}={driver.value:.4g}: {driver.description}"


def _condition_labels(
    conditions: tuple[StrategyCondition, ...],
) -> tuple[NonEmptyString, ...]:
    return tuple(f"{condition.name}: {condition.description}" for condition in conditions)


def _normalize_probabilities(probabilities: DirectionProbabilities) -> DirectionProbabilities:
    total = probabilities.up + probabilities.flat + probabilities.down
    if total <= 0:
        return DirectionProbabilities(up=0.0, flat=1.0, down=0.0)
    up = probabilities.up / total
    flat = probabilities.flat / total
    down = max(0.0, 1.0 - up - flat)
    return DirectionProbabilities(up=up, flat=flat, down=down)


def _grade_for_signal(
    confidence: float,
    probabilities: DirectionProbabilities,
    final_signal: FinalSignal,
) -> str:
    if final_signal is FinalSignal.ABSTAIN:
        return "N"
    dominant_probability = max(probabilities.up, probabilities.flat, probabilities.down)
    if confidence >= 0.75 and dominant_probability >= 0.60:
        return "A"
    if confidence >= 0.55 and dominant_probability >= 0.45:
        return "B"
    return "C"
