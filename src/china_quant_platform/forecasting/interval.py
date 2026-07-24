"""Empirical return interval forecasts from similar market regimes."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from pydantic import Field

from china_quant_platform.domain import Bar, DirectionProbabilities
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import ModelVersion, NonEmptyString

SIMILAR_REGIME_INTERVAL_MODEL: ModelVersion = "forecast.similar_regime_interval.v2"
SHORT_TERM_FORECAST_HORIZON_DAYS = 5
LONG_TERM_FORECAST_HORIZON_DAYS = 10
DEFAULT_INTERVAL_FORECAST_SECURITY_IDS: tuple[NonEmptyString, ...] = (
    "SSE:600519",
    "SSE:600036",
    "SSE:601318",
    "SSE:600276",
    "SZSE:000858",
    "SZSE:000333",
    "SZSE:002475",
    "SZSE:300750",
    "SSE:510300",
    "SSE:510500",
    "SSE:512100",
    "SSE:512880",
    "SSE:515790",
    "SSE:516160",
    "SSE:513300",
    "SZSE:159915",
    "SSE:518880",
    "SSE:511010",
    "SSE:511260",
    "SSE:000001",
    "SZSE:399001",
    "SSE:000300",
)


def forecast_horizon_days_for_mode(strategy_mode: str) -> int:
    """Return the validated endpoint horizon without changing strategy holding rules."""

    normalized = strategy_mode.strip().lower()
    if normalized == "short_term":
        return SHORT_TERM_FORECAST_HORIZON_DAYS
    if normalized == "long_term":
        return LONG_TERM_FORECAST_HORIZON_DAYS
    raise ValueError(f"unsupported strategy mode: {strategy_mode}")


class IntervalForecastValidation(DomainModel):
    sample_count: int = Field(ge=0)
    candidate_count: int = Field(default=0, ge=0)
    evaluation_stride: int = Field(default=1, ge=1)
    training_embargo: int = Field(default=0, ge=0)
    interval_coverage: float | None = Field(default=None, ge=0, le=1)
    downside_breach_rate: float | None = Field(default=None, ge=0, le=1)
    direction_brier_score: float | None = Field(default=None, ge=0)
    median_absolute_error: float | None = Field(default=None, ge=0)
    lower_tail_adjustment: float = Field(default=0.0, ge=0)
    upper_tail_adjustment: float = Field(default=0.0, ge=0)


class IntervalForecastResult(DomainModel):
    model_version: ModelVersion = SIMILAR_REGIME_INTERVAL_MODEL
    horizon: int = Field(ge=1)
    sample_count: int = Field(ge=0)
    similar_sample_count: int = Field(ge=0)
    direction_probabilities: DirectionProbabilities
    expected_return_quantiles: dict[str, float] = Field(default_factory=dict)
    expected_drawdown: float | None = None
    confidence: float = Field(ge=0, le=1)
    regime_score: float = Field(ge=-1, le=1)
    validation: IntervalForecastValidation | None = None
    notes: tuple[NonEmptyString, ...] = ()


class SecurityIntervalValidation(DomainModel):
    security_id: NonEmptyString
    forecast: IntervalForecastResult
    validation: IntervalForecastValidation | None = None


class IntervalForecastValidationReport(DomainModel):
    model_version: ModelVersion = SIMILAR_REGIME_INTERVAL_MODEL
    horizon: int = Field(ge=1)
    security_count: int = Field(ge=0)
    validated_security_count: int = Field(ge=0)
    minimum_validation_sample_count: int = Field(default=0, ge=0)
    average_validation_sample_count: float | None = Field(default=None, ge=0)
    average_interval_coverage: float | None = Field(default=None, ge=0, le=1)
    average_downside_breach_rate: float | None = Field(default=None, ge=0, le=1)
    average_direction_brier_score: float | None = Field(default=None, ge=0)
    average_median_absolute_error: float | None = Field(default=None, ge=0)
    average_lower_tail_adjustment: float | None = Field(default=None, ge=0)
    average_upper_tail_adjustment: float | None = Field(default=None, ge=0)
    reliability_label: NonEmptyString
    results: tuple[SecurityIntervalValidation, ...] = ()
    notes: tuple[NonEmptyString, ...] = ()


@dataclass(frozen=True, slots=True)
class _FeatureVector:
    short_momentum: float
    medium_momentum: float
    long_momentum: float
    trend_strength: float
    slope_score: float
    volatility: float
    drawdown: float
    volume_ratio: float
    rsi_score: float


@dataclass(frozen=True, slots=True)
class _HistoricalOutcome:
    features: _FeatureVector
    future_return: float
    future_drawdown: float


@dataclass(frozen=True, slots=True)
class _ForecastDistribution:
    similar_sample_count: int
    direction_probabilities: DirectionProbabilities
    quantiles: dict[str, float]
    expected_drawdown: float
    confidence: float
    distances: tuple[float, ...]


def forecast_interval_from_bars(
    bars: Sequence[Bar],
    *,
    horizon_days: int,
    round_trip_cost_bps: float = 15.0,
    min_samples: int = 40,
    max_similar_samples: int = 90,
) -> IntervalForecastResult:
    """Estimate forward return distribution from historically similar regimes.

    The result is a probabilistic engineering estimate. It avoids future data by only
    comparing the latest feature vector with historical points whose future horizon is
    already known inside the supplied bar history.
    """

    sorted_bars = tuple(sorted(bars, key=lambda item: item.end_time))
    closes = tuple(bar.close_price for bar in sorted_bars)
    if horizon_days < 1:
        raise ValueError("horizon_days must be at least 1")
    fallback = _fallback_result(horizon_days=horizon_days, sample_count=0)
    if len(closes) < max(80, horizon_days + 65):
        return fallback.model_copy(
            update={
                "sample_count": max(0, len(closes) - horizon_days),
                "notes": (f"历史K线不足，无法形成可靠预测区间：{len(closes)} bars。",),
            }
        )

    current = _features_at(len(closes) - 1, bars=sorted_bars, closes=closes)
    if current is None:
        return fallback.model_copy(update={"notes": ("当前特征不可计算，预测区间降级。",)})

    cost = round_trip_cost_bps / 10_000.0
    outcomes: list[_HistoricalOutcome] = []
    for index in range(64, len(closes) - horizon_days):
        features = _features_at(index, bars=sorted_bars, closes=closes)
        if features is None or closes[index] <= 0:
            continue
        future_window = closes[index + 1 : index + horizon_days + 1]
        if not future_window:
            continue
        future_return = closes[index + horizon_days] / closes[index] - 1.0 - cost
        future_drawdown = min(value / closes[index] - 1.0 for value in future_window) - cost
        outcomes.append(
            _HistoricalOutcome(
                features=features,
                future_return=future_return,
                future_drawdown=future_drawdown,
            )
        )

    if len(outcomes) < min_samples:
        return fallback.model_copy(
            update={
                "sample_count": len(outcomes),
                "notes": (f"可校准历史样本不足：{len(outcomes)}/{min_samples}。",),
            }
        )

    distribution = _forecast_distribution(
        current=current,
        outcomes=tuple(outcomes),
        min_samples=min_samples,
        max_similar_samples=max_similar_samples,
    )
    if distribution is None:
        return fallback.model_copy(
            update={
                "sample_count": len(outcomes),
                "notes": (f"可校准历史样本不足：{len(outcomes)}/{min_samples}。",),
            }
        )
    regime_score = _regime_score(current)
    validation = _validate_interval_forecasts(
        outcomes=tuple(outcomes),
        horizon_days=horizon_days,
        min_samples=min_samples,
        max_similar_samples=max_similar_samples,
    )
    notes = [
        (
            f"预测区间来自{distribution.similar_sample_count}/{len(outcomes)}个历史相似样本，"
            f"已扣除约{round_trip_cost_bps:.0f}bp往返成本。"
        ),
        "特征包含短中长动量、趋势斜率、波动、回撤、RSI和成交量确认。",
        f"当前状态分数{regime_score:.2f}，置信度{distribution.confidence:.0%}；区间不是确定未来价格。",
    ]
    if validation is not None and validation.interval_coverage is not None:
        notes.append(
            "清除重叠后的滚动校准："
            f"{validation.sample_count}个独立时点/"
            f"{validation.candidate_count}个候选时点；"
            f"步长{validation.evaluation_stride}日；"
            f"区间覆盖{validation.interval_coverage:.0%}；"
            f"下破率{validation.downside_breach_rate or 0.0:.0%}；"
            f"三分类Brier {validation.direction_brier_score or 0.0:.3f}。"
        )
    quantiles = _calibrated_quantiles(distribution.quantiles, validation)
    if validation is not None and quantiles != distribution.quantiles:
        notes.append(
            "区间已按滚动历史误差保守校正："
            f"下沿-{validation.lower_tail_adjustment:.2%}，"
            f"上沿+{validation.upper_tail_adjustment:.2%}。"
        )
    return IntervalForecastResult(
        horizon=horizon_days,
        sample_count=len(outcomes),
        similar_sample_count=distribution.similar_sample_count,
        direction_probabilities=distribution.direction_probabilities,
        expected_return_quantiles=quantiles,
        expected_drawdown=distribution.expected_drawdown,
        confidence=distribution.confidence,
        regime_score=regime_score,
        validation=validation,
        notes=tuple(notes),
    )


def validate_interval_forecast_universe(
    bars_by_security: Mapping[str, Sequence[Bar]],
    *,
    horizon_days: int,
    round_trip_cost_bps: float = 15.0,
    min_samples: int = 40,
    max_similar_samples: int = 90,
) -> IntervalForecastValidationReport:
    if horizon_days < 1:
        raise ValueError("horizon_days must be at least 1")
    results = tuple(
        SecurityIntervalValidation(
            security_id=security_id,
            forecast=forecast,
            validation=forecast.validation,
        )
        for security_id, bars in sorted(bars_by_security.items())
        for forecast in (
            forecast_interval_from_bars(
                bars,
                horizon_days=horizon_days,
                round_trip_cost_bps=round_trip_cost_bps,
                min_samples=min_samples,
                max_similar_samples=max_similar_samples,
            ),
        )
    )
    validations = tuple(item.validation for item in results if item.validation is not None)
    validation_sample_counts = tuple(item.sample_count for item in validations)
    coverage = _average_optional(item.interval_coverage for item in validations)
    downside = _average_optional(item.downside_breach_rate for item in validations)
    brier = _average_optional(item.direction_brier_score for item in validations)
    median_error = _average_optional(item.median_absolute_error for item in validations)
    lower_adjustment = _average_optional(item.lower_tail_adjustment for item in validations)
    upper_adjustment = _average_optional(item.upper_tail_adjustment for item in validations)
    label = _validation_reliability_label(
        validated_count=len(validations),
        horizon_days=horizon_days,
        minimum_sample_count=min(validation_sample_counts, default=0),
        coverage=coverage,
        downside=downside,
        brier=brier,
    )
    notes = [
        f"已验证{len(validations)}/{len(results)}个标的；预测区间仍为概率估计，不保证收益。",
    ]
    if coverage is not None:
        notes.append(
            "校准已清除持有期重叠并只统计不重叠时点；"
            f"最少{min(validation_sample_counts, default=0)}个、"
            f"平均{_mean(validation_sample_counts):.1f}个有效样本，"
            f"平均区间覆盖{coverage:.0%}，平均下破率{(downside or 0.0):.0%}，"
            f"平均三分类Brier {(brier or 0.0):.3f}。"
        )
    else:
        notes.append("有效校准样本不足，暂不能形成跨标的可靠性判断。")
    return IntervalForecastValidationReport(
        horizon=horizon_days,
        security_count=len(results),
        validated_security_count=len(validations),
        minimum_validation_sample_count=min(validation_sample_counts, default=0),
        average_validation_sample_count=(
            _mean(validation_sample_counts) if validation_sample_counts else None
        ),
        average_interval_coverage=coverage,
        average_downside_breach_rate=downside,
        average_direction_brier_score=brier,
        average_median_absolute_error=median_error,
        average_lower_tail_adjustment=lower_adjustment,
        average_upper_tail_adjustment=upper_adjustment,
        reliability_label=label,
        results=results,
        notes=tuple(notes),
    )


def _fallback_result(*, horizon_days: int, sample_count: int) -> IntervalForecastResult:
    return IntervalForecastResult(
        horizon=horizon_days,
        sample_count=sample_count,
        similar_sample_count=0,
        direction_probabilities=DirectionProbabilities(up=0.25, flat=0.50, down=0.25),
        expected_return_quantiles={},
        expected_drawdown=None,
        confidence=0.0,
        regime_score=0.0,
        notes=("预测区间暂不可用。",),
    )


def _features_at(
    index: int,
    *,
    bars: Sequence[Bar],
    closes: Sequence[float],
) -> _FeatureVector | None:
    if index < 64 or closes[index] <= 0:
        return None
    close = closes[index]
    short_momentum = close / closes[index - 5] - 1.0 if closes[index - 5] > 0 else 0.0
    medium_momentum = close / closes[index - 21] - 1.0 if closes[index - 21] > 0 else 0.0
    long_momentum = close / closes[index - 63] - 1.0 if closes[index - 63] > 0 else 0.0
    ma20 = _mean(closes[index - 19 : index + 1])
    ma60 = _mean(closes[index - 59 : index + 1])
    trend_strength = close / ma60 - 1.0 if ma60 > 0 else 0.0
    slope_score = _linear_slope_score(closes[index - 59 : index + 1])
    returns = _period_returns(closes[index - 40 : index + 1])
    volatility = _std(returns) * math.sqrt(252.0)
    peak = max(closes[index - 63 : index + 1])
    drawdown = close / peak - 1.0 if peak > 0 else 0.0
    volume_ratio = _volume_ratio(index, bars=bars, window=20)
    rsi_score = (_rsi(closes[index - 14 : index + 1]) - 50.0) / 50.0
    return _FeatureVector(
        short_momentum=short_momentum,
        medium_momentum=medium_momentum,
        long_momentum=long_momentum,
        trend_strength=trend_strength + (ma20 / ma60 - 1.0 if ma60 > 0 else 0.0),
        slope_score=slope_score,
        volatility=volatility,
        drawdown=drawdown,
        volume_ratio=volume_ratio,
        rsi_score=rsi_score,
    )


def _feature_distance(current: _FeatureVector, sample: _FeatureVector) -> float:
    return (
        1.10 * abs(current.medium_momentum - sample.medium_momentum) / 0.12
        + 0.90 * abs(current.long_momentum - sample.long_momentum) / 0.25
        + 1.00 * abs(current.trend_strength - sample.trend_strength) / 0.12
        + 0.80 * abs(current.slope_score - sample.slope_score)
        + 0.75 * abs(current.volatility - sample.volatility) / 0.35
        + 0.60 * abs(current.drawdown - sample.drawdown) / 0.20
        + 0.45 * abs(math.log(max(current.volume_ratio, 0.05) / max(sample.volume_ratio, 0.05)))
        + 0.45 * abs(current.rsi_score - sample.rsi_score)
    ) / 6.05


def _forecast_distribution(
    *,
    current: _FeatureVector,
    outcomes: Sequence[_HistoricalOutcome],
    min_samples: int,
    max_similar_samples: int,
) -> _ForecastDistribution | None:
    if len(outcomes) < min_samples:
        return None
    ranked = sorted(
        ((_feature_distance(current, outcome.features), outcome) for outcome in outcomes),
        key=lambda item: item[0],
    )
    similar_count = min(max(min_samples, len(ranked) // 3), max_similar_samples, len(ranked))
    similar = tuple(ranked[:similar_count])
    weights = tuple(math.exp(-3.0 * distance) for distance, _outcome in similar)
    returns = tuple(outcome.future_return for _distance, outcome in similar)
    drawdowns = tuple(outcome.future_drawdown for _distance, outcome in similar)
    quantiles = {
        "p05": _weighted_quantile(returns, weights, 0.05),
        "p50": _weighted_quantile(returns, weights, 0.50),
        "p95": _weighted_quantile(returns, weights, 0.95),
    }
    return _ForecastDistribution(
        similar_sample_count=similar_count,
        direction_probabilities=_direction_probabilities(
            returns=returns,
            weights=weights,
            sample_count=similar_count,
            current=current,
        ),
        quantiles=quantiles,
        expected_drawdown=_weighted_quantile(drawdowns, weights, 0.20),
        confidence=_confidence(
            sample_count=similar_count,
            distances=tuple(item[0] for item in similar),
        ),
        distances=tuple(item[0] for item in similar),
    )


def _validate_interval_forecasts(
    *,
    outcomes: Sequence[_HistoricalOutcome],
    horizon_days: int,
    min_samples: int,
    max_similar_samples: int,
    max_validation_points: int = 1260,
) -> IntervalForecastValidation | None:
    if horizon_days < 1:
        raise ValueError("horizon_days must be at least 1")
    first_eligible = min_samples + horizon_days - 1
    if len(outcomes) <= first_eligible:
        return None
    start = max(first_eligible, len(outcomes) - max_validation_points)
    stride = horizon_days
    alignment = (len(outcomes) - 1 - start) % stride
    evaluation_indices = tuple(range(start + alignment, len(outcomes), stride))
    if not evaluation_indices:
        return None
    covered = 0
    downside_breaches = 0
    brier_sum = 0.0
    median_abs_sum = 0.0
    lower_shortfalls: list[float] = []
    upper_shortfalls: list[float] = []
    evaluated = 0
    for index in evaluation_indices:
        actual = outcomes[index]
        # At origin ``index`` only labels ending no later than that origin are known.
        # The embargo removes the latest ``horizon_days - 1`` overlapping outcomes.
        training_end = index - horizon_days + 1
        distribution = _forecast_distribution(
            current=actual.features,
            outcomes=outcomes[:training_end],
            min_samples=min_samples,
            max_similar_samples=max_similar_samples,
        )
        if distribution is None:
            continue
        p05 = distribution.quantiles["p05"]
        p50 = distribution.quantiles["p50"]
        p95 = distribution.quantiles["p95"]
        if p05 <= actual.future_return <= p95:
            covered += 1
        if actual.future_return < p05:
            downside_breaches += 1
        lower_shortfalls.append(max(p05 - actual.future_return, 0.0))
        upper_shortfalls.append(max(actual.future_return - p95, 0.0))
        probabilities = distribution.direction_probabilities
        observed = _direction_outcome(actual.future_return)
        brier_sum += (
            (probabilities.up - observed[0]) ** 2
            + (probabilities.flat - observed[1]) ** 2
            + (probabilities.down - observed[2]) ** 2
        ) / 3.0
        median_abs_sum += abs(p50 - actual.future_return)
        evaluated += 1

    if evaluated == 0:
        return None
    return IntervalForecastValidation(
        sample_count=evaluated,
        candidate_count=len(outcomes) - start,
        evaluation_stride=stride,
        training_embargo=horizon_days,
        interval_coverage=covered / evaluated,
        downside_breach_rate=downside_breaches / evaluated,
        direction_brier_score=brier_sum / evaluated,
        median_absolute_error=median_abs_sum / evaluated,
        lower_tail_adjustment=_quantile(tuple(sorted(lower_shortfalls)), 0.90),
        upper_tail_adjustment=_quantile(tuple(sorted(upper_shortfalls)), 0.90),
    )


def _calibrated_quantiles(
    quantiles: dict[str, float],
    validation: IntervalForecastValidation | None,
) -> dict[str, float]:
    if validation is None or not quantiles:
        return quantiles
    p05 = quantiles.get("p05")
    p50 = quantiles.get("p50")
    p95 = quantiles.get("p95")
    if p05 is None or p50 is None or p95 is None:
        return quantiles
    lower = min(p50, p05 - validation.lower_tail_adjustment)
    upper = max(p50, p95 + validation.upper_tail_adjustment)
    return {"p05": lower, "p50": p50, "p95": upper}


def _average_optional(values: Iterable[float | None]) -> float | None:
    clean = tuple(value for value in values if value is not None)
    if not clean:
        return None
    return sum(clean) / len(clean)


def _validation_reliability_label(
    *,
    validated_count: int,
    horizon_days: int,
    minimum_sample_count: int,
    coverage: float | None,
    downside: float | None,
    brier: float | None,
) -> str:
    required_samples = required_independent_validation_samples(horizon_days)
    if (
        validated_count < 3
        or minimum_sample_count < required_samples
        or coverage is None
        or downside is None
        or brier is None
    ):
        return "INSUFFICIENT"
    if coverage >= 0.78 and downside <= 0.12 and brier <= 0.22:
        return "HIGH"
    if coverage >= 0.68 and downside <= 0.22 and brier <= 0.30:
        return "MEDIUM"
    return "LOW"


def required_independent_validation_samples(horizon_days: int) -> int:
    """Return the minimum number of non-overlapping forecast checks for a horizon."""

    if horizon_days < 1:
        raise ValueError("horizon_days must be at least 1")
    return max(5, min(40, math.ceil(840 / horizon_days)))


def _direction_outcome(future_return: float) -> tuple[float, float, float]:
    if future_return > 0.003:
        return (1.0, 0.0, 0.0)
    if future_return < -0.003:
        return (0.0, 0.0, 1.0)
    return (0.0, 1.0, 0.0)


def _direction_probabilities(
    *,
    returns: Sequence[float],
    weights: Sequence[float],
    sample_count: int,
    current: _FeatureVector,
) -> DirectionProbabilities:
    up_weight = sum(weight for value, weight in zip(returns, weights, strict=True) if value > 0.003)
    down_weight = sum(
        weight for value, weight in zip(returns, weights, strict=True) if value < -0.003
    )
    total = max(sum(weights), 1e-12)
    up = up_weight / total
    down = down_weight / total
    flat = max(0.0, 1.0 - up - down)
    regime = _regime_score(current)
    up = _clamp_probability(up + max(regime, 0.0) * 0.06)
    down = _clamp_probability(down + max(-regime, 0.0) * 0.06)
    flat = max(0.05, flat)
    shrink = min(0.35, 10.0 / max(sample_count, 1))
    up = up * (1.0 - shrink) + (1.0 / 3.0) * shrink
    flat = flat * (1.0 - shrink) + (1.0 / 3.0) * shrink
    down = down * (1.0 - shrink) + (1.0 / 3.0) * shrink
    total = up + flat + down
    return DirectionProbabilities(up=up / total, flat=flat / total, down=down / total)


def _regime_score(features: _FeatureVector) -> float:
    return _clamp(
        0.25 * _clamp(features.medium_momentum / 0.10)
        + 0.20 * _clamp(features.long_momentum / 0.22)
        + 0.22 * _clamp(features.trend_strength / 0.10)
        + 0.15 * features.slope_score
        + 0.10 * _clamp((features.volume_ratio - 1.0) / 0.70)
        + 0.08 * features.rsi_score
        - 0.12 * min(features.volatility / 0.65, 1.0)
        - 0.08 * min(abs(min(features.drawdown, 0.0)) / 0.25, 1.0)
    )


def _confidence(*, sample_count: int, distances: Sequence[float]) -> float:
    sample_component = min(sample_count / 80.0, 1.0)
    distance_component = 1.0 / (1.0 + 3.0 * (_mean(distances) if distances else 1.0))
    return max(0.0, min(1.0, 0.45 * sample_component + 0.55 * distance_component))


def _weighted_quantile(
    values: Sequence[float],
    weights: Sequence[float],
    probability: float,
) -> float:
    pairs = sorted(zip(values, weights, strict=True), key=lambda item: item[0])
    total_weight = sum(weight for _value, weight in pairs)
    if total_weight <= 0:
        return pairs[0][0] if pairs else 0.0
    threshold = total_weight * probability
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return pairs[-1][0]


def _quantile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = probability * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _linear_slope_score(values: Sequence[float]) -> float:
    if len(values) < 2 or any(value <= 0 for value in values):
        return 0.0
    logs = tuple(math.log(value) for value in values)
    x_mean = (len(logs) - 1) / 2.0
    y_mean = _mean(logs)
    denominator = sum((index - x_mean) ** 2 for index in range(len(logs)))
    if denominator <= 0:
        return 0.0
    slope = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(logs))
    slope /= denominator
    returns = _period_returns(values)
    daily_volatility = _std(returns)
    if daily_volatility <= 1e-12:
        return 0.0
    return _clamp(slope / daily_volatility * math.sqrt(252.0))


def _rsi(values: Sequence[float]) -> float:
    returns = _period_returns(values)
    gains = [value for value in returns if value > 0]
    losses = [-value for value in returns if value < 0]
    average_gain = _mean(gains)
    average_loss = _mean(losses)
    if average_loss <= 1e-12:
        return 100.0 if average_gain > 0 else 50.0
    relative_strength = average_gain / average_loss
    return 100.0 - 100.0 / (1.0 + relative_strength)


def _volume_ratio(index: int, *, bars: Sequence[Bar], window: int) -> float:
    if not bars or index <= 0:
        return 1.0
    start = max(0, index - window)
    previous = tuple(bar.volume for bar in bars[start:index] if bar.volume > 0)
    if not previous:
        return 1.0
    baseline = _mean(previous)
    if baseline <= 0:
        return 1.0
    return max(bars[index].volume, 0.0) / baseline


def _period_returns(values: Sequence[float]) -> tuple[float, ...]:
    return tuple(
        current / previous - 1.0
        for previous, current in zip(values, values[1:], strict=False)
        if previous > 0 and current > 0
    )


def _std(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _clamp_probability(value: float) -> float:
    return max(0.02, min(0.92, value))
