"""Deterministic technical indicators and reproducible cache keys."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import Field

from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import NonEmptyString
from china_quant_platform.domain.models import Bar

type IndicatorValue = float | None
type NumericValue = float | int | None
type CacheParameter = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class MacdResult:
    macd: tuple[IndicatorValue, ...]
    signal: tuple[IndicatorValue, ...]
    histogram: tuple[IndicatorValue, ...]


@dataclass(frozen=True, slots=True)
class BollingerBands:
    lower: tuple[IndicatorValue, ...]
    middle: tuple[IndicatorValue, ...]
    upper: tuple[IndicatorValue, ...]


class IndicatorCacheKey(DomainModel):
    """Versioned, stable cache identity for an indicator output."""

    indicator_name: NonEmptyString
    version: NonEmptyString
    security_id: NonEmptyString
    interval: NonEmptyString
    data_snapshot_id: NonEmptyString
    parameters: dict[str, CacheParameter] = Field(default_factory=dict)
    adjustment: NonEmptyString = "NONE"
    input_fingerprint: NonEmptyString = "unspecified"

    def digest(self) -> str:
        return stable_cache_digest("indicator", self.to_contract_dict())

    def key(self) -> str:
        return f"{self.indicator_name}:{self.version}:{self.digest()}"


class IndicatorSpec(DomainModel):
    """Small public descriptor used by engines and tests to build cache keys."""

    name: NonEmptyString
    version: NonEmptyString
    parameters: dict[str, CacheParameter] = Field(default_factory=dict)
    minimum_samples: int = Field(ge=1)

    def cache_key(
        self,
        *,
        security_id: str,
        interval: str,
        data_snapshot_id: str,
        adjustment: str = "NONE",
        input_fingerprint: str = "unspecified",
    ) -> IndicatorCacheKey:
        return IndicatorCacheKey(
            indicator_name=self.name,
            version=self.version,
            security_id=security_id,
            interval=interval,
            data_snapshot_id=data_snapshot_id,
            parameters=dict(self.parameters),
            adjustment=adjustment,
            input_fingerprint=input_fingerprint,
        )


def stable_cache_digest(namespace: str, payload: Mapping[str, Any]) -> str:
    """Return a SHA256 digest that is stable across dict insertion order."""

    normalized = _normalize_cache_value({"namespace": namespace, "payload": payload})
    encoded = json.dumps(
        normalized,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def series_fingerprint(values: Sequence[NumericValue]) -> str:
    cleaned = [_clean_value(value) for value in values]
    return stable_cache_digest("series", {"values": cleaned})


def sma(
    values: Sequence[NumericValue],
    window: int,
    *,
    min_periods: int | None = None,
) -> tuple[IndicatorValue, ...]:
    window = _validate_window(window)
    required = _validate_min_periods(min_periods, window)
    cleaned = tuple(_clean_value(value) for value in values)
    output: list[IndicatorValue] = []

    for index in range(len(cleaned)):
        trailing = _valid_trailing_values(cleaned, index, window)
        output.append(_mean(trailing) if len(trailing) >= required else None)

    return tuple(output)


def ema(
    values: Sequence[NumericValue],
    span: int,
    *,
    min_periods: int | None = None,
) -> tuple[IndicatorValue, ...]:
    span = _validate_window(span, name="span")
    required = _validate_min_periods(min_periods, span)
    alpha = 2.0 / (span + 1.0)
    current_ema: float | None = None
    observed = 0
    output: list[IndicatorValue] = []

    for raw_value in values:
        value = _clean_value(raw_value)
        if value is None:
            output.append(None)
            continue

        observed += 1
        current_ema = value if current_ema is None else alpha * value + (1.0 - alpha) * current_ema
        output.append(current_ema if observed >= required else None)

    return tuple(output)


def macd(
    values: Sequence[NumericValue],
    *,
    fast_span: int = 12,
    slow_span: int = 26,
    signal_span: int = 9,
) -> MacdResult:
    fast_span = _validate_window(fast_span, name="fast_span")
    slow_span = _validate_window(slow_span, name="slow_span")
    signal_span = _validate_window(signal_span, name="signal_span")
    if fast_span >= slow_span:
        raise ValueError("fast_span must be smaller than slow_span")

    fast = ema(values, fast_span)
    slow = ema(values, slow_span)
    macd_line = tuple(
        fast_value - slow_value if fast_value is not None and slow_value is not None else None
        for fast_value, slow_value in zip(fast, slow, strict=True)
    )
    signal_line = ema(macd_line, signal_span)
    histogram = tuple(
        macd_value - signal_value if macd_value is not None and signal_value is not None else None
        for macd_value, signal_value in zip(macd_line, signal_line, strict=True)
    )
    return MacdResult(macd=macd_line, signal=signal_line, histogram=histogram)


def rsi(values: Sequence[NumericValue], window: int = 14) -> tuple[IndicatorValue, ...]:
    window = _validate_window(window)
    cleaned = tuple(_clean_value(value) for value in values)
    differences: list[IndicatorValue] = [None]
    for previous, current in zip(cleaned, cleaned[1:], strict=False):
        differences.append(None if previous is None or current is None else current - previous)

    output: list[IndicatorValue] = []
    for index in range(len(cleaned)):
        if index < window:
            output.append(None)
            continue
        trailing = differences[index - window + 1 : index + 1]
        if len(trailing) < window or any(value is None for value in trailing):
            output.append(None)
            continue
        numeric = [value for value in trailing if value is not None]
        gains = [max(value, 0.0) for value in numeric]
        losses = [abs(min(value, 0.0)) for value in numeric]
        average_gain = _mean(gains)
        average_loss = _mean(losses)
        if average_loss == 0.0:
            output.append(100.0 if average_gain > 0.0 else 50.0)
        else:
            relative_strength_value = average_gain / average_loss
            output.append(100.0 - (100.0 / (1.0 + relative_strength_value)))

    return tuple(output)


def atr(
    bars: Sequence[Bar],
    window: int = 14,
    *,
    min_periods: int | None = None,
) -> tuple[IndicatorValue, ...]:
    window = _validate_window(window)
    true_ranges: list[IndicatorValue] = []
    previous_close: float | None = None

    for bar in bars:
        high = _clean_value(bar.high_price)
        low = _clean_value(bar.low_price)
        close = _clean_value(bar.close_price)
        if high is None or low is None or close is None:
            true_ranges.append(None)
            previous_close = close
            continue

        if previous_close is None:
            true_range = high - low
        else:
            true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))
        true_ranges.append(true_range)
        previous_close = close

    return sma(true_ranges, window, min_periods=min_periods)


def bollinger_bands(
    values: Sequence[NumericValue],
    window: int = 20,
    *,
    deviations: float = 2.0,
    min_periods: int | None = None,
) -> BollingerBands:
    window = _validate_window(window)
    if deviations <= 0:
        raise ValueError("deviations must be positive")
    required = _validate_min_periods(min_periods, window)
    cleaned = tuple(_clean_value(value) for value in values)
    lower: list[IndicatorValue] = []
    middle: list[IndicatorValue] = []
    upper: list[IndicatorValue] = []

    for index in range(len(cleaned)):
        trailing = _valid_trailing_values(cleaned, index, window)
        if len(trailing) < required:
            lower.append(None)
            middle.append(None)
            upper.append(None)
            continue
        mean_value = _mean(trailing)
        std_value = _population_std(trailing)
        lower.append(mean_value - deviations * std_value)
        middle.append(mean_value)
        upper.append(mean_value + deviations * std_value)

    return BollingerBands(lower=tuple(lower), middle=tuple(middle), upper=tuple(upper))


def vwap(
    bars: Sequence[Bar],
    *,
    window: int | None = None,
    min_periods: int | None = None,
) -> tuple[IndicatorValue, ...]:
    if window is not None:
        window = _validate_window(window)
    required = _validate_min_periods(min_periods, window or 1)
    output: list[IndicatorValue] = []

    for index in range(len(bars)):
        start = 0 if window is None else max(0, index - window + 1)
        trailing = bars[start : index + 1]
        valid_pairs = [
            (bar.amount, bar.volume)
            for bar in trailing
            if _clean_value(bar.amount) is not None
            and _clean_value(bar.volume) is not None
            and bar.volume > 0
        ]
        if len(valid_pairs) < required:
            output.append(None)
            continue
        total_amount = sum(amount for amount, _volume in valid_pairs)
        total_volume = sum(volume for _amount, volume in valid_pairs)
        output.append(total_amount / total_volume if total_volume > 0 else None)

    return tuple(output)


def returns(values: Sequence[NumericValue], *, periods: int = 1) -> tuple[IndicatorValue, ...]:
    periods = _validate_window(periods, name="periods")
    cleaned = tuple(_clean_value(value) for value in values)
    output: list[IndicatorValue] = []
    for index, current in enumerate(cleaned):
        if index < periods:
            output.append(None)
            continue
        previous = cleaned[index - periods]
        if current is None or previous is None or previous == 0.0:
            output.append(None)
        else:
            output.append(current / previous - 1.0)
    return tuple(output)


def rolling_volatility(
    values: Sequence[NumericValue],
    window: int,
    *,
    periods: int = 1,
    annualization: float | None = None,
) -> tuple[IndicatorValue, ...]:
    window = _validate_window(window)
    period_returns = returns(values, periods=periods)
    scale = math.sqrt(annualization) if annualization is not None else 1.0
    output: list[IndicatorValue] = []
    for index in range(len(period_returns)):
        trailing = _valid_trailing_values(period_returns, index, window)
        output.append(_population_std(trailing) * scale if len(trailing) >= window else None)
    return tuple(output)


def downside_volatility(
    values: Sequence[NumericValue],
    window: int,
    *,
    periods: int = 1,
    minimum_acceptable_return: float = 0.0,
    annualization: float | None = None,
) -> tuple[IndicatorValue, ...]:
    window = _validate_window(window)
    period_returns = returns(values, periods=periods)
    scale = math.sqrt(annualization) if annualization is not None else 1.0
    output: list[IndicatorValue] = []
    for index in range(len(period_returns)):
        trailing = _valid_trailing_values(period_returns, index, window)
        if len(trailing) < window:
            output.append(None)
            continue
        downside = [min(value - minimum_acceptable_return, 0.0) for value in trailing]
        output.append(_population_std(downside) * scale)
    return tuple(output)


def drawdown(values: Sequence[NumericValue]) -> tuple[IndicatorValue, ...]:
    running_peak: float | None = None
    output: list[IndicatorValue] = []
    for raw_value in values:
        value = _clean_value(raw_value)
        if value is None:
            output.append(None)
            continue
        running_peak = value if running_peak is None else max(running_peak, value)
        output.append(0.0 if running_peak == 0.0 else value / running_peak - 1.0)
    return tuple(output)


def relative_strength(
    values: Sequence[NumericValue],
    benchmark_values: Sequence[NumericValue],
    *,
    window: int,
) -> tuple[IndicatorValue, ...]:
    window = _validate_window(window)
    if len(values) != len(benchmark_values):
        raise ValueError("values and benchmark_values must have the same length")

    subject_returns = returns(values, periods=window)
    benchmark_returns = returns(benchmark_values, periods=window)
    return tuple(
        subject - benchmark if subject is not None and benchmark is not None else None
        for subject, benchmark in zip(subject_returns, benchmark_returns, strict=True)
    )


def _validate_window(window: int, *, name: str = "window") -> int:
    if window < 1:
        raise ValueError(f"{name} must be at least 1")
    return window


def _validate_min_periods(min_periods: int | None, window: int) -> int:
    required = window if min_periods is None else min_periods
    if required < 1:
        raise ValueError("min_periods must be at least 1")
    if required > window:
        raise ValueError("min_periods cannot exceed window")
    return required


def _clean_value(value: NumericValue) -> IndicatorValue:
    if value is None:
        return None
    normalized = float(value)
    return normalized if math.isfinite(normalized) else None


def _valid_trailing_values(
    values: Sequence[IndicatorValue],
    index: int,
    window: int,
) -> list[float]:
    start = max(0, index - window + 1)
    return [value for value in values[start : index + 1] if value is not None]


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _population_std(values: Sequence[float]) -> float:
    mean_value = _mean(values)
    return math.sqrt(sum((value - mean_value) ** 2 for value in values) / len(values))


def _normalize_cache_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _normalize_cache_value(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple | list):
        return [_normalize_cache_value(item) for item in value]
    return value
