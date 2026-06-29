"""Deterministic indicator tests."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import pytest

from china_quant_platform.domain import (
    AdjustmentMode,
    Bar,
    BarInterval,
    RecordQualityStatus,
)
from china_quant_platform.indicators import (
    IndicatorSpec,
    atr,
    bollinger_bands,
    drawdown,
    ema,
    macd,
    relative_strength,
    returns,
    rolling_volatility,
    rsi,
    series_fingerprint,
    sma,
    vwap,
)


def make_bar(
    index: int,
    *,
    high: float,
    low: float,
    close: float,
    volume: float = 100.0,
    amount: float | None = None,
) -> Bar:
    start = datetime(2026, 1, 1, 9, 30, tzinfo=UTC) + timedelta(days=index)
    end = start + timedelta(hours=5, minutes=30)
    actual_amount = close * volume if amount is None else amount
    return Bar(
        security_id="SSE:600519",
        interval=BarInterval.DAILY,
        start_time=start,
        end_time=end,
        trade_date=date(2026, 1, 1) + timedelta(days=index),
        open_price=close,
        high_price=high,
        low_price=low,
        close_price=close,
        volume=volume,
        amount=actual_amount,
        adjustment=AdjustmentMode.NONE,
        provider="fixture",
        schema_version="v1",
        source_time=end,
        observed_at=end,
        received_at=end + timedelta(minutes=1),
        quality_status=RecordQualityStatus.OK,
    )


def test_sma_and_ema_enforce_warmup_and_missing_values() -> None:
    assert sma([1, 2, 3, 4], 3) == (None, None, 2.0, 3.0)
    assert sma([1, None, 3, 4], 2) == (None, None, None, 3.5)
    assert sma([1, None, 3, 4], 2, min_periods=1) == (1.0, 1.0, 3.0, 3.5)
    assert ema([1, 2, 3], 3) == (None, None, 2.25)


def test_macd_rsi_atr_bollinger_and_vwap_are_aligned() -> None:
    values = tuple(float(index) for index in range(1, 41))
    macd_result = macd(values)
    assert len(macd_result.macd) == len(values)
    assert macd_result.macd[:25] == (None,) * 25
    assert macd_result.signal[:33] == (None,) * 33
    assert macd_result.histogram[33] is not None

    assert rsi([1, 2, 3], window=2) == (None, None, 100.0)
    assert rsi([3, 2, 1], window=2) == (None, None, 0.0)
    assert rsi([1, None, 3], window=2) == (None, None, None)

    bars = (
        make_bar(0, high=12, low=9, close=10),
        make_bar(1, high=13, low=10, close=12),
        make_bar(2, high=14, low=11, close=13),
    )
    assert atr(bars, window=2) == (None, 3.0, 3.0)

    bands = bollinger_bands([1, 2, 3], window=3)
    expected_std = math.sqrt(2.0 / 3.0)
    assert bands.middle == (None, None, 2.0)
    assert bands.lower[2] == pytest.approx(2.0 - 2.0 * expected_std)
    assert bands.upper[2] == pytest.approx(2.0 + 2.0 * expected_std)

    vwap_bars = (
        make_bar(0, high=10, low=10, close=10, volume=100, amount=1_000),
        make_bar(1, high=12, low=12, close=12, volume=200, amount=2_400),
        make_bar(2, high=13, low=13, close=13, volume=300, amount=3_900),
    )
    assert vwap(vwap_bars) == pytest.approx((10.0, 3_400 / 300, 7_300 / 600))
    assert vwap(vwap_bars, window=2) == pytest.approx((None, 3_400 / 300, 6_300 / 500))


def test_return_volatility_drawdown_and_relative_strength() -> None:
    one_period_returns = returns([100, 110, None, 121])
    assert one_period_returns[0] is None
    assert one_period_returns[1] == pytest.approx(0.1)
    assert one_period_returns[2:] == (None, None)

    two_period_returns = returns([100, 110, None, 121], periods=2)
    assert two_period_returns[:3] == (None, None, None)
    assert two_period_returns[3] == pytest.approx(0.1)

    volatility = rolling_volatility([100, 110, 99, 108.9], window=2)
    assert volatility == pytest.approx((None, None, 0.1, 0.1))

    assert drawdown([100, 120, 90, 130]) == pytest.approx((0.0, 0.0, -0.25, 0.0))

    strength = relative_strength(
        [100, 110, 121],
        [100, 105, 110.25],
        window=2,
    )
    assert strength == pytest.approx((None, None, 0.1075))


def test_indicators_do_not_access_future_values() -> None:
    base = [10, 11, 12, 13, 1_000]
    changed_future = [10, 11, 12, 13, 14]

    assert sma(base, 2)[:4] == sma(changed_future, 2)[:4]
    assert ema(base, 3)[:4] == ema(changed_future, 3)[:4]
    assert rsi(base, window=2)[:4] == rsi(changed_future, window=2)[:4]
    assert returns(base)[:4] == returns(changed_future)[:4]
    assert (
        rolling_volatility(base, window=2)[:4] == rolling_volatility(changed_future, window=2)[:4]
    )


def test_indicator_cache_key_is_reproducible() -> None:
    spec_a = IndicatorSpec(
        name="technical.sma.v1",
        version="v1",
        minimum_samples=20,
        parameters={"window": 20, "min_periods": 20},
    )
    spec_b = IndicatorSpec(
        name="technical.sma.v1",
        version="v1",
        minimum_samples=20,
        parameters={"min_periods": 20, "window": 20},
    )
    fingerprint = series_fingerprint([1, 2, 3])

    key_a = spec_a.cache_key(
        security_id="SSE:600519",
        interval="1d",
        data_snapshot_id="snapshot-001",
        input_fingerprint=fingerprint,
    ).key()
    key_b = spec_b.cache_key(
        security_id="SSE:600519",
        interval="1d",
        data_snapshot_id="snapshot-001",
        input_fingerprint=fingerprint,
    ).key()

    assert key_a == key_b
    assert key_a.startswith("technical.sma.v1:v1:")
