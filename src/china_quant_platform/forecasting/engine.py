"""Calibrated probability forecasts and abstain gates."""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from china_quant_platform.domain import DirectionProbabilities
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import ModelVersion, NonEmptyString

ABSTAIN_STATEMENT = "Forecast abstains; probabilities are shown only as diagnostic estimates."
READY_STATEMENT = "Forecast is probabilistic and interval based; it does not guarantee returns."


class ForecastStatus(StrEnum):
    READY = "READY"
    ABSTAIN = "ABSTAIN"


class AbstainTrigger(StrEnum):
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    OUT_OF_DISTRIBUTION = "OUT_OF_DISTRIBUTION"
    DRIFT = "DRIFT"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


class ForecastConfig(DomainModel):
    horizon: int = Field(ge=1)
    model_version: ModelVersion
    min_samples: int = Field(default=60, ge=1)
    max_ood_score: float = Field(default=0.8, ge=0, le=1)
    max_drift_score: float = Field(default=0.5, ge=0, le=1)
    min_direction_confidence: float = Field(default=0.45, ge=0, le=1)
    flat_probability_floor: float = Field(default=0.10, ge=0, le=1)


class LogisticCalibrator(DomainModel):
    intercept: float = 0.0
    slope: float = 1.0

    def probability(self, raw_score: float) -> float:
        value = self.intercept + self.slope * raw_score
        return 1.0 / (1.0 + math.exp(-value))


class ForecastResult(DomainModel):
    status: ForecastStatus
    horizon: int = Field(ge=1)
    model_version: ModelVersion
    direction_probabilities: DirectionProbabilities | None = None
    expected_return_quantiles: dict[str, float] = Field(default_factory=dict)
    expected_drawdown: float | None = None
    abstain_reasons: tuple[AbstainTrigger, ...] = ()
    statement: NonEmptyString

    @model_validator(mode="after")
    def ready_requires_probabilities(self) -> Self:
        if self.status is ForecastStatus.READY and self.direction_probabilities is None:
            raise ValueError("READY forecasts require direction_probabilities")
        if self.status is ForecastStatus.ABSTAIN and not self.abstain_reasons:
            raise ValueError("ABSTAIN forecasts require abstain_reasons")
        return self


class CalibrationMetrics(DomainModel):
    sample_count: int = Field(ge=0)
    brier_score: float | None = Field(default=None, ge=0)
    log_loss: float | None = Field(default=None, ge=0)
    expected_calibration_error: float | None = Field(default=None, ge=0, le=1)


class ForecastEngine:
    def __init__(
        self,
        *,
        config: ForecastConfig,
        calibrator: LogisticCalibrator | None = None,
    ) -> None:
        self._config = config
        self._calibrator = calibrator or LogisticCalibrator()

    def predict(
        self,
        *,
        raw_score: float,
        sample_count: int,
        ood_score: float,
        drift_score: float,
        return_samples: tuple[float, ...],
    ) -> ForecastResult:
        abstain_reasons = _abstain_reasons(
            config=self._config,
            sample_count=sample_count,
            ood_score=ood_score,
            drift_score=drift_score,
        )
        probabilities = _direction_probabilities(
            up_probability=self._calibrator.probability(raw_score),
            raw_score=raw_score,
            flat_floor=self._config.flat_probability_floor,
        )
        if (
            max(probabilities.up, probabilities.flat, probabilities.down)
            < self._config.min_direction_confidence
        ):
            abstain_reasons = (*abstain_reasons, AbstainTrigger.LOW_CONFIDENCE)

        quantiles = _return_quantiles(return_samples)
        expected_drawdown = min(return_samples) if return_samples else None
        if abstain_reasons:
            return ForecastResult(
                status=ForecastStatus.ABSTAIN,
                horizon=self._config.horizon,
                model_version=self._config.model_version,
                direction_probabilities=probabilities,
                expected_return_quantiles=quantiles,
                expected_drawdown=expected_drawdown,
                abstain_reasons=abstain_reasons,
                statement=ABSTAIN_STATEMENT,
            )
        return ForecastResult(
            status=ForecastStatus.READY,
            horizon=self._config.horizon,
            model_version=self._config.model_version,
            direction_probabilities=probabilities,
            expected_return_quantiles=quantiles,
            expected_drawdown=expected_drawdown,
            statement=READY_STATEMENT,
        )


def calibration_metrics(
    probabilities: tuple[float, ...],
    outcomes: tuple[int, ...],
    *,
    bins: int = 10,
) -> CalibrationMetrics:
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must have the same length")
    if bins < 1:
        raise ValueError("bins must be at least 1")
    if not probabilities:
        return CalibrationMetrics(sample_count=0)
    clipped = tuple(min(max(probability, 1e-12), 1.0 - 1e-12) for probability in probabilities)
    brier = sum(
        (probability - outcome) ** 2 for probability, outcome in zip(clipped, outcomes, strict=True)
    ) / len(clipped)
    log_loss = -sum(
        outcome * math.log(probability) + (1 - outcome) * math.log(1.0 - probability)
        for probability, outcome in zip(clipped, outcomes, strict=True)
    ) / len(clipped)
    ece = expected_calibration_error(clipped, outcomes, bins=bins)
    return CalibrationMetrics(
        sample_count=len(clipped),
        brier_score=brier,
        log_loss=log_loss,
        expected_calibration_error=ece,
    )


def expected_calibration_error(
    probabilities: tuple[float, ...],
    outcomes: tuple[int, ...],
    *,
    bins: int = 10,
) -> float:
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must have the same length")
    total = len(probabilities)
    if total == 0:
        return 0.0
    error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        if index == bins - 1:
            in_bin = [
                (probability, outcome)
                for probability, outcome in zip(probabilities, outcomes, strict=True)
                if lower <= probability <= upper
            ]
        else:
            in_bin = [
                (probability, outcome)
                for probability, outcome in zip(probabilities, outcomes, strict=True)
                if lower <= probability < upper
            ]
        if not in_bin:
            continue
        confidence = sum(probability for probability, _outcome in in_bin) / len(in_bin)
        accuracy = sum(outcome for _probability, outcome in in_bin) / len(in_bin)
        error += len(in_bin) / total * abs(accuracy - confidence)
    return error


def _abstain_reasons(
    *,
    config: ForecastConfig,
    sample_count: int,
    ood_score: float,
    drift_score: float,
) -> tuple[AbstainTrigger, ...]:
    reasons: list[AbstainTrigger] = []
    if sample_count < config.min_samples:
        reasons.append(AbstainTrigger.INSUFFICIENT_HISTORY)
    if ood_score > config.max_ood_score:
        reasons.append(AbstainTrigger.OUT_OF_DISTRIBUTION)
    if drift_score > config.max_drift_score:
        reasons.append(AbstainTrigger.DRIFT)
    return tuple(reasons)


def _direction_probabilities(
    *,
    up_probability: float,
    raw_score: float,
    flat_floor: float,
) -> DirectionProbabilities:
    flat = min(max(flat_floor * (1.0 - min(abs(raw_score), 1.0)), 0.0), 0.8)
    directional_mass = 1.0 - flat
    up = up_probability * directional_mass
    down = (1.0 - up_probability) * directional_mass
    return DirectionProbabilities(up=up, flat=flat, down=down)


def _return_quantiles(samples: tuple[float, ...]) -> dict[str, float]:
    if not samples:
        return {}
    sorted_samples = tuple(sorted(samples))
    return {
        "p05": _quantile(sorted_samples, 0.05),
        "p50": _quantile(sorted_samples, 0.50),
        "p95": _quantile(sorted_samples, 0.95),
    }


def _quantile(sorted_samples: tuple[float, ...], probability: float) -> float:
    if len(sorted_samples) == 1:
        return sorted_samples[0]
    position = probability * (len(sorted_samples) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_samples[lower]
    weight = position - lower
    return sorted_samples[lower] * (1.0 - weight) + sorted_samples[upper] * weight
