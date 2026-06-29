"""Tests for calibrated forecasts and abstain gates."""

from __future__ import annotations

import math

import pytest

from china_quant_platform.forecasting import (
    AbstainTrigger,
    ForecastConfig,
    ForecastEngine,
    ForecastStatus,
    LogisticCalibrator,
    calibration_metrics,
)


def test_logistic_forecast_ready_returns_probabilities_and_quantiles() -> None:
    engine = ForecastEngine(
        config=ForecastConfig(
            horizon=5,
            model_version="forecast-demo-v1",
            min_samples=3,
            min_direction_confidence=0.40,
        ),
        calibrator=LogisticCalibrator(intercept=0.0, slope=2.0),
    )

    result = engine.predict(
        raw_score=0.5,
        sample_count=100,
        ood_score=0.1,
        drift_score=0.1,
        return_samples=(-0.03, 0.0, 0.02, 0.05, 0.08),
    )

    assert result.status is ForecastStatus.READY
    assert result.direction_probabilities is not None
    probabilities = result.direction_probabilities
    assert math.isclose(probabilities.up + probabilities.flat + probabilities.down, 1.0)
    assert probabilities.up > probabilities.down
    assert result.expected_return_quantiles == pytest.approx(
        {"p05": -0.024, "p50": 0.02, "p95": 0.074}
    )
    assert result.expected_drawdown == -0.03
    assert "does not guarantee" in result.statement


def test_forecast_abstains_for_sample_ood_drift_and_low_confidence() -> None:
    engine = ForecastEngine(
        config=ForecastConfig(
            horizon=20,
            model_version="forecast-demo-v1",
            min_samples=60,
            max_ood_score=0.5,
            max_drift_score=0.4,
            min_direction_confidence=0.95,
        )
    )

    result = engine.predict(
        raw_score=0.0,
        sample_count=10,
        ood_score=0.8,
        drift_score=0.9,
        return_samples=(),
    )

    assert result.status is ForecastStatus.ABSTAIN
    assert result.direction_probabilities is not None
    assert result.abstain_reasons == (
        AbstainTrigger.INSUFFICIENT_HISTORY,
        AbstainTrigger.OUT_OF_DISTRIBUTION,
        AbstainTrigger.DRIFT,
        AbstainTrigger.LOW_CONFIDENCE,
    )
    assert result.expected_return_quantiles == {}
    assert result.expected_drawdown is None
    assert "diagnostic estimates" in result.statement


def test_calibration_metrics_include_brier_logloss_ece() -> None:
    metrics = calibration_metrics(probabilities=(0.8, 0.2), outcomes=(1, 0), bins=2)

    assert metrics.sample_count == 2
    assert metrics.brier_score == pytest.approx(0.04)
    assert metrics.log_loss == pytest.approx(-math.log(0.8))
    assert metrics.expected_calibration_error == pytest.approx(0.2)


def test_calibration_metrics_reject_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        calibration_metrics(probabilities=(0.8,), outcomes=(1, 0))
