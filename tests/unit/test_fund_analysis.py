"""Off-exchange fund analysis and confirmation tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from china_quant_platform.domain import (
    EstimatedFundNav,
    FundNav,
    RecordQualityStatus,
)
from china_quant_platform.funds import (
    FundConfirmationRule,
    FundFeeSchedule,
    FundOrderRequest,
    FundOrderType,
    FundRiskLevel,
    analyze_off_exchange_fund,
    confirm_fund_order,
)


def official_nav(fund_id: str, nav_date: date, unit_nav: float) -> FundNav:
    published_at = datetime.combine(nav_date, time(20, 0), tzinfo=UTC)
    return FundNav(
        fund_id=fund_id,
        nav_date=nav_date,
        unit_nav=unit_nav,
        accumulated_nav=unit_nav,
        published_at=published_at,
        provider="fixture",
        schema_version="v1",
        source_time=published_at,
        observed_at=published_at,
        received_at=published_at + timedelta(minutes=1),
        quality_status=RecordQualityStatus.OK,
    )


def estimated_nav(fund_id: str, nav_date: date, value: float) -> EstimatedFundNav:
    source = datetime.combine(nav_date, time(14, 30), tzinfo=UTC)
    return EstimatedFundNav(
        fund_id=fund_id,
        nav_date=nav_date,
        estimated_unit_nav=value,
        confidence=0.8,
        provider="fixture",
        schema_version="v1",
        source_time=source,
        observed_at=source,
        received_at=source + timedelta(minutes=1),
        quality_status=RecordQualityStatus.OK,
    )


def nav_history(fund_id: str = "FUND:000001") -> tuple[FundNav, ...]:
    return (
        official_nav(fund_id, date(2026, 5, 1), 1.00),
        official_nav(fund_id, date(2026, 5, 20), 0.95),
        official_nav(fund_id, date(2026, 5, 25), 1.05),
        official_nav(fund_id, date(2026, 6, 1), 1.10),
    )


def test_subscription_confirmation_uses_official_nav_and_fee_before_cutoff() -> None:
    confirmation = confirm_fund_order(
        order=FundOrderRequest(
            fund_id="FUND:000001",
            order_type=FundOrderType.SUBSCRIBE,
            submitted_at=datetime(2026, 6, 1, 14, 30, tzinfo=UTC),
            amount=10_000.0,
        ),
        navs=nav_history(),
        fee_schedule=FundFeeSchedule(subscription_fee_rate=0.015),
        confirmation_rule=FundConfirmationRule(cutoff_time=time(15, 0)),
    )

    assert confirmation.effective_nav_date == date(2026, 6, 1)
    assert confirmation.official_unit_nav == 1.10
    assert confirmation.fee == pytest.approx(150.0)
    assert confirmation.confirmed_shares == pytest.approx((10_000.0 - 150.0) / 1.10)
    assert "official NAV" in confirmation.note


def test_subscription_after_cutoff_uses_next_available_official_nav() -> None:
    confirmation = confirm_fund_order(
        order=FundOrderRequest(
            fund_id="FUND:000001",
            order_type=FundOrderType.SUBSCRIBE,
            submitted_at=datetime(2026, 5, 24, 15, 30, tzinfo=UTC),
            amount=1_000.0,
        ),
        navs=nav_history(),
        fee_schedule=FundFeeSchedule(),
    )

    assert confirmation.effective_nav_date == date(2026, 5, 25)
    assert confirmation.official_unit_nav == 1.05


def test_redemption_confirmation_returns_cash_after_official_nav_fee() -> None:
    confirmation = confirm_fund_order(
        order=FundOrderRequest(
            fund_id="FUND:000001",
            order_type=FundOrderType.REDEEM,
            submitted_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
            shares=1_000.0,
        ),
        navs=nav_history(),
        fee_schedule=FundFeeSchedule(redemption_fee_rate=0.005),
    )

    assert confirmation.confirmed_shares == 1_000.0
    assert confirmation.confirmed_cash_amount == pytest.approx(1_100.0 * (1 - 0.005))
    assert confirmation.fee == pytest.approx(5.5)


def test_estimated_nav_cannot_enter_confirmation_or_analysis() -> None:
    estimate = estimated_nav("FUND:000001", date(2026, 6, 1), 1.12)

    with pytest.raises(ValueError, match="EstimatedFundNav"):
        confirm_fund_order(
            order=FundOrderRequest(
                fund_id="FUND:000001",
                order_type=FundOrderType.SUBSCRIBE,
                submitted_at=datetime(2026, 6, 1, 14, 30, tzinfo=UTC),
                amount=1_000.0,
            ),
            navs=(*nav_history(), estimate),
            fee_schedule=FundFeeSchedule(),
        )

    with pytest.raises(ValueError, match="EstimatedFundNav"):
        analyze_off_exchange_fund(
            fund_id="FUND:000001",
            navs=(*nav_history(), estimate),
            fee_schedule=FundFeeSchedule(),
        )


def test_fund_analysis_uses_official_nav_risk_fees_and_benchmark_comparison() -> None:
    report = analyze_off_exchange_fund(
        fund_id="FUND:000001",
        navs=nav_history(),
        benchmark_navs=(
            official_nav("FUND:BENCH", date(2026, 5, 1), 1.00),
            official_nav("FUND:BENCH", date(2026, 5, 20), 0.99),
            official_nav("FUND:BENCH", date(2026, 5, 25), 1.02),
            official_nav("FUND:BENCH", date(2026, 6, 1), 1.05),
        ),
        fee_schedule=FundFeeSchedule(
            management_fee_rate_annual=0.012,
            custody_fee_rate_annual=0.0024,
        ),
    )

    assert report.as_of == date(2026, 6, 1)
    assert report.latest_official_nav == 1.10
    assert report.weekly_return == pytest.approx(1.10 / 1.05 - 1.0)
    assert report.monthly_return == pytest.approx(0.10)
    assert report.max_drawdown == pytest.approx(0.05)
    assert report.benchmark_return == pytest.approx(0.05)
    assert report.excess_return == pytest.approx(0.05)
    assert report.fee_drag_estimate == pytest.approx(0.0144 / 12.0)
    assert report.risk_level is FundRiskLevel.HIGH
