"""Data quality gate tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from china_quant_platform.data import (
    BarsRequest,
    DataQualityCheck,
    DataQualityPolicy,
    DataQualityReport,
    DataQualityService,
)
from china_quant_platform.domain import (
    AdjustmentMode,
    Bar,
    BarInterval,
    DataHealthStatus,
    DataInvalid,
    DataStale,
    Quote,
    RecordQualityStatus,
    UnauthorizedData,
)


def aware_datetime(day: int = 22, hour: int = 9, minute: int = 30) -> datetime:
    return datetime(2026, 6, day, hour, minute, tzinfo=UTC)


def make_daily_bar(day: int) -> Bar:
    start_time = aware_datetime(day, 9, 30)
    end_time = aware_datetime(day, 15, 0)
    return Bar(
        security_id="SSE:600519",
        interval=BarInterval.DAILY,
        start_time=start_time,
        end_time=end_time,
        trade_date=date(2026, 6, day),
        open_price=100,
        high_price=103,
        low_price=99,
        close_price=102,
        volume=10_000,
        amount=1_000_000,
        adjustment=AdjustmentMode.NONE,
        provider="fixture",
        schema_version="v1",
        source_time=end_time,
        observed_at=end_time,
        received_at=end_time + timedelta(seconds=1),
        quality_status=RecordQualityStatus.OK,
    )


def make_quote() -> Quote:
    source_time = aware_datetime(22, 14, 59)
    return Quote(
        security_id="SSE:600519",
        latest_price=102,
        previous_close=100,
        open_price=101,
        high_price=103,
        low_price=99,
        volume=10_000,
        amount=1_020_000,
        provider="fixture",
        schema_version="v1",
        source_time=source_time,
        observed_at=source_time,
        received_at=source_time + timedelta(seconds=1),
        quality_status=RecordQualityStatus.OK,
    )


def daily_request(start_day: int, end_day: int) -> BarsRequest:
    return BarsRequest(
        security_id="SSE:600519",
        interval=BarInterval.DAILY,
        start_time=aware_datetime(start_day, 9, 30),
        end_time=aware_datetime(end_day, 16, 0),
    )


def issue_codes(report: DataQualityReport) -> set[str]:
    return {issue.code for issue in report.issues}


def test_data_quality_detects_duplicate_bars_and_blocks_signal() -> None:
    service = DataQualityService()
    bar = make_daily_bar(22)

    report = service.evaluate_bars([bar, bar], as_of=aware_datetime(22, 15, 1))

    assert report.health.status is DataHealthStatus.INVALID
    assert report.health.block_signal is True
    assert "DQ-01-DUPLICATE-BAR" in issue_codes(report)
    with pytest.raises(DataInvalid):
        service.assert_signal_allowed(report)


def test_data_quality_detects_invalid_bar_ohlc() -> None:
    service = DataQualityService()
    invalid_bar = make_daily_bar(22).model_copy(update={"high_price": 101})

    report = service.evaluate_bars([invalid_bar], as_of=aware_datetime(22, 15, 1))

    assert report.health.status is DataHealthStatus.INVALID
    assert "DQ-03-BAR-OHLC" in issue_codes(report)


def test_data_quality_detects_missing_expected_bars() -> None:
    service = DataQualityService()
    bars = [make_daily_bar(22), make_daily_bar(24)]

    report = service.evaluate_bars(
        bars,
        as_of=aware_datetime(24, 15, 1),
        request=daily_request(22, 24),
    )

    assert report.health.status is DataHealthStatus.INVALID
    assert "DQ-04-MISSING-BARS" in issue_codes(report)


def test_data_quality_detects_stale_quote_and_raises_typed_error() -> None:
    service = DataQualityService(DataQualityPolicy(quote_stale_after=timedelta(seconds=5)))
    quote = make_quote()

    report = service.evaluate_quote(
        quote,
        as_of=quote.source_time + timedelta(seconds=6),
    )

    assert report.health.status is DataHealthStatus.STALE
    assert report.health.block_signal is True
    with pytest.raises(DataStale):
        service.assert_signal_allowed(report)


def test_data_quality_detects_unauthorized_provider() -> None:
    service = DataQualityService()
    quote = make_quote()

    report = service.evaluate_quote(
        quote,
        as_of=quote.source_time + timedelta(seconds=1),
        authorized_providers={"licensed_provider"},
    )

    assert report.health.status is DataHealthStatus.UNAUTHORIZED
    assert "DQ-AUTH-PROVIDER" in issue_codes(report)
    with pytest.raises(UnauthorizedData):
        service.assert_signal_allowed(report)


def test_data_quality_detects_missing_required_quote_fields() -> None:
    service = DataQualityService()
    payload = make_quote().model_dump(mode="python")
    del payload["provider"]
    malformed_quote = Quote.model_construct(**payload)

    report = service.evaluate_quote(
        malformed_quote,
        as_of=aware_datetime(22, 15, 0),
    )

    assert report.health.status is DataHealthStatus.INVALID
    assert "DQ-MISSING-FIELD" in issue_codes(report)


def test_data_quality_reconciles_cross_source_quote_mismatch() -> None:
    service = DataQualityService(
        DataQualityPolicy(cross_source_price_tolerance=0.01),
    )
    primary = make_quote()
    secondary = primary.model_copy(
        update={
            "latest_price": primary.latest_price * 1.2,
            "provider": "second_source",
        }
    )

    report = service.reconcile_quotes(
        primary,
        secondary,
        as_of=primary.source_time + timedelta(seconds=1),
    )

    assert report.health.status is DataHealthStatus.INVALID
    assert "DQ-06-PRICE-MISMATCH" in issue_codes(report)


def test_data_quality_reports_healthy_data_when_checks_pass() -> None:
    service = DataQualityService()

    report = service.evaluate_bars(
        [make_daily_bar(22), make_daily_bar(23), make_daily_bar(24)],
        as_of=aware_datetime(24, 15, 1),
        request=daily_request(22, 24),
        authorized_providers={"fixture"},
    )

    assert report.health.status is DataHealthStatus.HEALTHY
    assert report.health.block_signal is False
    assert report.issues == ()
    service.assert_signal_allowed(report)


def test_quality_check_enum_values_are_contract_stable() -> None:
    assert DataQualityCheck.FRESHNESS.value == "FRESHNESS"
