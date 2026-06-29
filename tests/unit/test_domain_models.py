"""Domain model invariant tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from china_quant_platform.domain import (
    AbstainReason,
    AdjustmentMode,
    AssetType,
    Bar,
    BarInterval,
    Currency,
    DataHealth,
    DataHealthStatus,
    DirectionProbabilities,
    EstimatedFundNav,
    Exchange,
    FinalSignal,
    FundNav,
    FundNavType,
    Quote,
    RecordQualityStatus,
    SecurityRef,
    SecurityStatus,
)


def aware_datetime(hour: int = 9, minute: int = 30) -> datetime:
    return datetime(2026, 6, 28, hour, minute, tzinfo=UTC)


def test_security_ref_rejects_delisting_before_listing() -> None:
    with pytest.raises(ValidationError):
        SecurityRef(
            security_id="SSE:600519",
            symbol="600519",
            name="Kweichow Moutai",
            asset_type=AssetType.STOCK,
            exchange=Exchange.SSE,
            currency=Currency.CNY,
            listed_date=date(2001, 8, 27),
            status_date=date(2001, 8, 27),
            status=SecurityStatus.DELISTED,
            delisted_date=date(2000, 1, 1),
        )


def test_quote_rejects_naive_source_time() -> None:
    with pytest.raises(ValidationError):
        Quote(
            security_id="SSE:600519",
            latest_price=100,
            previous_close=99,
            open_price=99,
            high_price=101,
            low_price=98,
            volume=1_000,
            amount=100_000,
            provider="fixture",
            schema_version="v1",
            source_time=datetime(2026, 6, 28, 9, 30),
            observed_at=aware_datetime(),
            received_at=aware_datetime(9, 31),
            quality_status=RecordQualityStatus.OK,
        )


def test_bar_rejects_invalid_ohlc() -> None:
    with pytest.raises(ValidationError):
        Bar(
            security_id="SSE:600519",
            interval=BarInterval.DAILY,
            start_time=aware_datetime(9, 30),
            end_time=aware_datetime(15, 0),
            trade_date=date(2026, 6, 28),
            open_price=100,
            high_price=101,
            low_price=99,
            close_price=102,
            volume=10_000,
            amount=1_000_000,
            adjustment=AdjustmentMode.NONE,
            provider="fixture",
            schema_version="v1",
            source_time=aware_datetime(15, 0),
            observed_at=aware_datetime(15, 0),
            received_at=aware_datetime(15, 1),
            quality_status=RecordQualityStatus.OK,
        )


def test_official_and_estimated_fund_nav_are_separate_types() -> None:
    official = FundNav(
        fund_id="FUND:000001",
        nav_date=date(2026, 6, 26),
        unit_nav=1.25,
        accumulated_nav=2.5,
        published_at=aware_datetime(20, 0),
        provider="fixture",
        schema_version="v1",
        source_time=aware_datetime(20, 0),
        observed_at=aware_datetime(20, 0),
        received_at=aware_datetime(20, 1),
        quality_status=RecordQualityStatus.OK,
    )
    estimate = EstimatedFundNav(
        fund_id="FUND:000001",
        nav_date=date(2026, 6, 26),
        estimated_unit_nav=1.23,
        confidence=0.7,
        provider="fixture",
        schema_version="v1",
        source_time=aware_datetime(14, 0),
        observed_at=aware_datetime(14, 0),
        received_at=aware_datetime(14, 1),
        quality_status=RecordQualityStatus.DEGRADED,
    )

    assert official.nav_type is FundNavType.OFFICIAL
    assert estimate.nav_type is FundNavType.ESTIMATED


def test_official_fund_nav_rejects_estimated_marker() -> None:
    with pytest.raises(ValidationError):
        FundNav(
            fund_id="FUND:000001",
            nav_date=date(2026, 6, 26),
            unit_nav=1.25,
            accumulated_nav=2.5,
            published_at=aware_datetime(20, 0),
            nav_type=FundNavType.ESTIMATED,
            provider="fixture",
            schema_version="v1",
            source_time=aware_datetime(20, 0),
            observed_at=aware_datetime(20, 0),
            received_at=aware_datetime(20, 1),
            quality_status=RecordQualityStatus.OK,
        )


def test_direction_probabilities_must_sum_to_one() -> None:
    with pytest.raises(ValidationError):
        DirectionProbabilities(up=0.8, flat=0.2, down=0.2)


def test_data_health_rejects_naive_as_of() -> None:
    with pytest.raises(ValidationError):
        DataHealth(
            status=DataHealthStatus.HEALTHY,
            block_signal=False,
            as_of=datetime(2026, 6, 28, 15, 0),
            issues=(),
        )


def test_report_time_window_helper_uses_aware_datetime() -> None:
    assert aware_datetime() + timedelta(minutes=1) > aware_datetime()


def test_abstain_reason_enum_uses_contract_value() -> None:
    assert AbstainReason.DATA.value == "DATA"
    assert FinalSignal.ABSTAIN.value == "ABSTAIN"
