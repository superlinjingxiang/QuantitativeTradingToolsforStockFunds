"""China market rule engine tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from china_quant_platform.domain import (
    AssetType,
    Currency,
    DataInvalid,
    EstimatedFundNav,
    Exchange,
    FundNav,
    RecordQualityStatus,
    RuleMissing,
    RuleReviewStatus,
    SecurityRef,
    SecurityRule,
    SecurityStatus,
)
from china_quant_platform.rules import InMemoryRuleRepository, MarketRuleEngine, OrderSide


def stock_rule(
    *,
    rule_id: str = "sse-stock-v1",
    effective_from: date = date(2020, 1, 1),
    effective_to: date | None = None,
    security_id: str | None = None,
    lot_size: int = 100,
    tick_size: float = 0.01,
    intraday_round_trip: bool = False,
    review_status: RuleReviewStatus = RuleReviewStatus.APPROVED,
    **extra: object,
) -> SecurityRule:
    defaults: dict[str, object] = {
        "limit_up_pct": 0.10,
        "limit_down_pct": 0.10,
        "commission_rate": 0.0003,
        "min_commission": 5.0,
        "transfer_fee_rate": 0.00001,
        "stamp_tax_rate": 0.0005,
    }
    defaults.update(extra)
    return SecurityRule(
        rule_id=rule_id,
        version="v1",
        exchange=Exchange.SSE,
        asset_type=AssetType.STOCK,
        security_id=security_id,
        effective_from=effective_from,
        effective_to=effective_to,
        lot_size=lot_size,
        tick_size=tick_size,
        intraday_round_trip=intraday_round_trip,
        source="fixture exchange rule",
        review_status=review_status,
        **defaults,
    )


def fund_rule() -> SecurityRule:
    return SecurityRule(
        rule_id="fund-official-nav-v1",
        version="v1",
        exchange=Exchange.FUND_COMPANY,
        asset_type=AssetType.MUTUAL_FUND,
        effective_from=date(2020, 1, 1),
        source="fixture fund document",
        review_status=RuleReviewStatus.APPROVED,
    )


def stock_security(security_id: str = "SSE:600519") -> SecurityRef:
    return SecurityRef(
        security_id=security_id,
        symbol=security_id.split(":")[1],
        name="fixture stock",
        asset_type=AssetType.STOCK,
        exchange=Exchange.SSE,
        currency=Currency.CNY,
        listed_date=date(2001, 1, 1),
        status_date=date(2026, 6, 22),
        status=SecurityStatus.ACTIVE,
    )


def aware_datetime(hour: int) -> datetime:
    return datetime(2026, 6, 22, hour, 0, tzinfo=UTC)


def official_nav() -> FundNav:
    published_at = aware_datetime(20)
    return FundNav(
        fund_id="FUND:000001",
        nav_date=date(2026, 6, 22),
        unit_nav=1.2,
        accumulated_nav=2.1,
        published_at=published_at,
        provider="fixture",
        schema_version="v1",
        source_time=published_at,
        observed_at=published_at,
        received_at=published_at + timedelta(seconds=1),
        quality_status=RecordQualityStatus.OK,
    )


def estimated_nav() -> EstimatedFundNav:
    observed_at = aware_datetime(14)
    return EstimatedFundNav(
        fund_id="FUND:000001",
        nav_date=date(2026, 6, 22),
        estimated_unit_nav=1.18,
        provider="fixture",
        schema_version="v1",
        source_time=observed_at,
        observed_at=observed_at,
        received_at=observed_at + timedelta(seconds=1),
        quality_status=RecordQualityStatus.DEGRADED,
    )


def test_repository_resolves_effective_date_boundaries() -> None:
    old_rule = stock_rule(
        rule_id="old",
        effective_from=date(2020, 1, 1),
        effective_to=date(2025, 12, 31),
        lot_size=100,
    )
    new_rule = stock_rule(rule_id="new", effective_from=date(2026, 1, 1), lot_size=200)
    repository = InMemoryRuleRepository([new_rule, old_rule])

    assert (
        repository.resolve(
            exchange=Exchange.SSE,
            asset_type=AssetType.STOCK,
            trade_date=date(2025, 12, 31),
        ).rule_id
        == "old"
    )
    assert (
        repository.resolve(
            exchange=Exchange.SSE,
            asset_type=AssetType.STOCK,
            trade_date=date(2026, 1, 1),
        ).rule_id
        == "new"
    )


def test_security_specific_rule_takes_precedence_over_generic_rule() -> None:
    generic = stock_rule(rule_id="generic", lot_size=100)
    specific = stock_rule(rule_id="specific", security_id="SSE:688001", lot_size=200)
    repository = InMemoryRuleRepository([generic, specific])

    resolved = repository.resolve(
        exchange=Exchange.SSE,
        asset_type=AssetType.STOCK,
        trade_date=date(2026, 6, 22),
        security_id="SSE:688001",
    )

    assert resolved.rule_id == "specific"
    assert resolved.lot_size == 200


def test_missing_or_unapproved_rule_fails_closed_without_prefix_guess() -> None:
    repository = InMemoryRuleRepository(
        [stock_rule(rule_id="draft", review_status=RuleReviewStatus.DRAFT)]
    )

    with pytest.raises(RuleMissing):
        repository.resolve(
            exchange=Exchange.SSE,
            asset_type=AssetType.STOCK,
            trade_date=date(2026, 6, 22),
            security_id="SSE:600519",
        )


def test_engine_resolves_from_security_identity() -> None:
    repository = InMemoryRuleRepository([stock_rule(security_id="SSE:600519")])
    engine = MarketRuleEngine(repository)

    assert engine.resolve(stock_security(), date(2026, 6, 22)).security_id == "SSE:600519"


def test_a_share_t_plus_one_blocks_same_day_bought_sell_quantity() -> None:
    rule = stock_rule(intraday_round_trip=False)
    engine = MarketRuleEngine(InMemoryRuleRepository([rule]))

    assert engine.sellable_quantity(rule, total_position=1000, bought_today=300) == 700
    result = engine.validate_order(
        rule,
        side=OrderSide.SELL,
        trade_date=date(2026, 6, 22),
        quantity=800,
        price=10.0,
        previous_close=10.0,
        total_position=1000,
        bought_today=300,
    )

    assert result.allowed is False
    assert "Sell quantity exceeds currently sellable quantity." in result.reasons


def test_limit_touch_without_opposite_liquidity_does_not_execute() -> None:
    rule = stock_rule()
    engine = MarketRuleEngine(InMemoryRuleRepository([rule]))

    result = engine.validate_order(
        rule,
        side=OrderSide.BUY,
        trade_date=date(2026, 6, 22),
        quantity=100,
        price=11.0,
        previous_close=10.0,
        has_opposite_liquidity=False,
    )

    assert result.allowed is False
    assert "Limit-up touch without sell-side liquidity is not executable." in result.reasons


def test_suspension_date_blocks_order() -> None:
    rule = stock_rule(suspension_dates=("2026-06-22",))
    engine = MarketRuleEngine(InMemoryRuleRepository([rule]))

    result = engine.validate_order(
        rule,
        side=OrderSide.BUY,
        trade_date=date(2026, 6, 22),
        quantity=100,
        price=10.0,
        previous_close=10.0,
    )

    assert result.allowed is False
    assert "Security is suspended on trade_date." in result.reasons


def test_lot_size_and_tick_size_are_enforced() -> None:
    rule = stock_rule()
    engine = MarketRuleEngine(InMemoryRuleRepository([rule]))

    result = engine.validate_order(
        rule,
        side=OrderSide.BUY,
        trade_date=date(2026, 6, 22),
        quantity=150,
        price=10.005,
        previous_close=10.0,
    )

    assert result.allowed is False
    assert "Order quantity must be a multiple of lot_size 100." in result.reasons
    assert "Order price must align to tick_size 0.01." in result.reasons


def test_fee_calculation_uses_side_specific_taxes() -> None:
    rule = stock_rule()
    engine = MarketRuleEngine(InMemoryRuleRepository([rule]))

    fees = engine.calculate_fees(rule, side=OrderSide.SELL, notional=10_000)

    assert fees.commission == pytest.approx(5.0)
    assert fees.transfer_fee == pytest.approx(0.1)
    assert fees.stamp_tax == pytest.approx(5.0)
    assert fees.total == pytest.approx(10.1)


def test_off_exchange_fund_rejects_estimated_nav_for_official_semantics() -> None:
    rule = fund_rule()
    engine = MarketRuleEngine(InMemoryRuleRepository([rule]))

    engine.ensure_off_exchange_fund_uses_official_nav(rule, official_nav())
    with pytest.raises(DataInvalid):
        engine.ensure_off_exchange_fund_uses_official_nav(rule, estimated_nav())


def test_information_is_not_visible_before_disclosure_time() -> None:
    engine = MarketRuleEngine(InMemoryRuleRepository([stock_rule()]))

    assert (
        engine.is_information_observable(
            available_at=aware_datetime(20),
            as_of=aware_datetime(15),
        )
        is False
    )
    assert (
        engine.is_information_observable(
            available_at=aware_datetime(20),
            as_of=aware_datetime(21),
        )
        is True
    )
