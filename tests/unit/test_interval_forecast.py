"""Tests for empirical similar-regime interval forecasts."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, date, datetime, timedelta

from china_quant_platform.data import BarsRequest
from china_quant_platform.domain import AdjustmentMode, Bar, BarInterval, RecordQualityStatus
from china_quant_platform.forecasting import (
    forecast_interval_from_bars,
    validate_interval_forecast_universe,
)
from china_quant_platform.forecasting.lab import validate_default_interval_forecast_universe


def test_interval_forecast_uses_similar_samples_for_probabilities_and_quantiles() -> None:
    bars = _bars_from_prices(_regime_prices(180))

    forecast = forecast_interval_from_bars(bars, horizon_days=21, round_trip_cost_bps=15.0)

    assert forecast.similar_sample_count >= 40
    assert forecast.sample_count >= forecast.similar_sample_count
    assert forecast.direction_probabilities.up > forecast.direction_probabilities.down
    assert math.isclose(
        forecast.direction_probabilities.up
        + forecast.direction_probabilities.flat
        + forecast.direction_probabilities.down,
        1.0,
    )
    assert forecast.expected_return_quantiles["p05"] <= forecast.expected_return_quantiles["p50"]
    assert forecast.expected_return_quantiles["p50"] <= forecast.expected_return_quantiles["p95"]
    assert forecast.expected_drawdown is not None
    assert forecast.expected_drawdown <= forecast.expected_return_quantiles["p95"]
    assert forecast.validation is not None
    assert forecast.validation.sample_count > 0
    assert forecast.validation.interval_coverage is not None
    assert 0.0 <= forecast.validation.interval_coverage <= 1.0
    assert forecast.validation.direction_brier_score is not None
    assert forecast.validation.direction_brier_score >= 0.0
    assert forecast.validation.lower_tail_adjustment >= 0.0
    assert forecast.validation.upper_tail_adjustment >= 0.0
    assert "历史相似样本" in forecast.notes[0]
    assert any("滚动校准" in note for note in forecast.notes)


def test_interval_forecast_degrades_when_history_is_insufficient() -> None:
    forecast = forecast_interval_from_bars(_bars_from_prices(_regime_prices(50)), horizon_days=21)

    assert forecast.similar_sample_count == 0
    assert forecast.expected_return_quantiles == {}
    assert forecast.expected_drawdown is None
    assert forecast.confidence == 0.0
    assert forecast.validation is None


def test_interval_forecast_universe_report_aggregates_validation_quality() -> None:
    bars_by_security = {
        "SSE:510300": _bars_from_prices(_regime_prices(190, drift=0.0011), "SSE:510300"),
        "SSE:513300": _bars_from_prices(_regime_prices(190, drift=0.0014), "SSE:513300"),
        "SZSE:159915": _bars_from_prices(_regime_prices(190, drift=0.0009), "SZSE:159915"),
        "SSE:511010": _bars_from_prices(_regime_prices(190, drift=0.0003), "SSE:511010"),
    }

    report = validate_interval_forecast_universe(bars_by_security, horizon_days=21)

    assert report.security_count == 4
    assert report.validated_security_count == 4
    assert report.average_interval_coverage is not None
    assert 0.0 <= report.average_interval_coverage <= 1.0
    assert report.average_direction_brier_score is not None
    assert report.average_direction_brier_score >= 0.0
    assert report.average_lower_tail_adjustment is not None
    assert report.average_lower_tail_adjustment >= 0.0
    assert report.average_upper_tail_adjustment is not None
    assert report.average_upper_tail_adjustment >= 0.0
    assert report.reliability_label in {"HIGH", "MEDIUM", "LOW", "INSUFFICIENT"}
    assert len(report.results) == 4
    assert "平均区间覆盖" in report.notes[-1]


def test_provider_backed_interval_forecast_lab_reports_failures() -> None:
    provider = _LabProvider(
        {
            "SSE:510300": _bars_from_prices(_regime_prices(190, drift=0.0011), "SSE:510300"),
            "SSE:513300": _bars_from_prices(_regime_prices(190, drift=0.0014), "SSE:513300"),
        }
    )

    report = asyncio.run(
        validate_default_interval_forecast_universe(
            provider,
            security_ids=("SSE:510300", "SSE:513300", "SSE:BAD"),
            horizon_days=21,
            history_years=2,
        )
    )

    assert report.security_count == 2
    assert report.validated_security_count == 2
    assert "请求3个标的，成功2个，失败1个" in report.notes[-2]
    assert "SSE:BAD" in report.notes[-1]


def _regime_prices(count: int, *, drift: float = 0.0014) -> tuple[float, ...]:
    prices: list[float] = []
    price = 1.0
    for index in range(count):
        cycle = math.sin(index / 11.0) * 0.0004
        price *= 1.0 + drift + cycle
        prices.append(price)
    return tuple(prices)


def _bars_from_prices(
    prices: tuple[float, ...],
    security_id: str = "SSE:513300",
) -> tuple[Bar, ...]:
    start = date(2025, 1, 2)
    bars: list[Bar] = []
    previous = prices[0]
    for offset, close in enumerate(prices):
        trade_date = start + timedelta(days=offset)
        timestamp = datetime.combine(trade_date, datetime.min.time(), tzinfo=UTC)
        high = max(previous, close) * 1.005
        low = min(previous, close) * 0.995
        volume = 1_000_000 + offset * 1_000
        bars.append(
            Bar(
                security_id=security_id,
                interval=BarInterval.DAILY,
                start_time=timestamp,
                end_time=timestamp + timedelta(hours=6),
                trade_date=trade_date,
                open_price=previous,
                high_price=high,
                low_price=low,
                close_price=close,
                volume=volume,
                amount=volume * close,
                adjustment=AdjustmentMode.NONE,
                provider="fixture",
                schema_version="v1",
                source_time=timestamp + timedelta(hours=6),
                observed_at=timestamp + timedelta(hours=6),
                received_at=timestamp + timedelta(hours=6, seconds=1),
                quality_status=RecordQualityStatus.OK,
            )
        )
        previous = close
    return tuple(bars)


class _LabProvider:
    provider_id = "lab_fixture"

    def __init__(self, bars_by_security: dict[str, tuple[Bar, ...]]) -> None:
        self._bars_by_security = bars_by_security

    async def get_bars(self, request: BarsRequest) -> list[Bar]:
        if request.security_id not in self._bars_by_security:
            raise KeyError(request.security_id)
        return list(self._bars_by_security[request.security_id])
