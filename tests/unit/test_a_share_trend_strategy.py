"""A-share multi-factor trend baseline tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from china_quant_platform.strategies import (
    AShareFactorSnapshot,
    AShareTrendConfig,
    AShareTrendStrategy,
    AShareUniverseMember,
    RawSignalIntent,
    ResearchStatus,
    StrategyContext,
    cross_sectional_percentile_ranks,
    summarize_group_returns,
)


def as_of() -> datetime:
    return datetime(2026, 2, 28, 15, 0, tzinfo=UTC)


def member(
    security_id: str,
    *,
    industry: str = "consumer",
    liquidity_score: float = 0.9,
    point_in_time_member: bool = True,
    eligible: bool = True,
    listed: bool = True,
    suspended: bool = False,
) -> AShareUniverseMember:
    return AShareUniverseMember(
        security_id=security_id,
        as_of=as_of(),
        industry=industry,
        point_in_time_member=point_in_time_member,
        eligible=eligible,
        listed=listed,
        suspended=suspended,
        liquidity_score=liquidity_score,
    )


def factors(
    *,
    visible_at: datetime | None = None,
    momentum: float = 0.6,
    trend_strength: float = 0.4,
    market_state_score: float = 0.3,
) -> AShareFactorSnapshot:
    return AShareFactorSnapshot(
        visible_at=visible_at or as_of(),
        value=0.5,
        quality=0.7,
        profitability=0.6,
        investment=0.4,
        momentum=momentum,
        relative_strength=0.6,
        low_volatility=0.5,
        liquidity=0.8,
        trend_strength=trend_strength,
        market_state_score=market_state_score,
    )


def test_cross_sectional_percentile_ranks_support_factor_direction() -> None:
    ranks = cross_sectional_percentile_ranks({"a": 1.0, "b": 3.0, "c": 2.0})
    inverse = cross_sectional_percentile_ranks(
        {"a": 1.0, "b": 3.0, "c": 2.0},
        higher_is_better=False,
    )

    assert ranks == {"a": 0.0, "c": 0.5, "b": 1.0}
    assert inverse == {"a": 1.0, "c": 0.5, "b": 0.0}


def test_a_share_trend_ranks_point_in_time_pool_and_rejects_invalid_inputs() -> None:
    strategy = AShareTrendStrategy(
        AShareTrendConfig(max_positions=2, min_market_state_score=0.0, min_trend_strength=0.0)
    )
    members = (
        member("SSE:600001", industry="consumer"),
        member("SSE:600002", industry="industrial"),
        member("SSE:600003", suspended=True),
        member("SSE:600004"),
        member("SSE:600005", point_in_time_member=False),
    )
    snapshots = {
        "SSE:600001": factors(momentum=0.8),
        "SSE:600002": factors(momentum=0.5),
        "SSE:600003": factors(momentum=0.9),
        "SSE:600004": factors(visible_at=as_of() + timedelta(days=1)),
        "SSE:600005": factors(momentum=0.9),
    }

    selection = strategy.rank_universe(members=members, factors=snapshots)

    assert selection.research_status is ResearchStatus.RESEARCH
    assert tuple(item.security_id for item in selection.selected) == ("SSE:600001", "SSE:600002")
    assert selection.selected[0].target_weight == pytest.approx(0.4)
    assert "suspended" in selection.rejected["SSE:600003"]
    assert selection.rejected["SSE:600004"] == ("factor_not_visible_at_as_of",)
    assert "not_in_point_in_time_universe" in selection.rejected["SSE:600005"]


def test_a_share_exit_logic_is_independent_from_buy_conditions() -> None:
    strategy = AShareTrendStrategy()

    hold = strategy.evaluate_exit(
        holding_return=0.03,
        position_drawdown=-0.02,
        trend_strength=0.1,
    )
    exit_decision = strategy.evaluate_exit(
        holding_return=-0.09,
        position_drawdown=-0.13,
        trend_strength=-0.3,
    )

    assert hold.intent is RawSignalIntent.HOLD_BIAS
    assert exit_decision.intent is RawSignalIntent.SELL_BIAS
    assert exit_decision.reasons == (
        "stop_loss_triggered",
        "position_drawdown_triggered",
        "trend_break_triggered",
    )


def test_a_share_strategy_emits_raw_signal_and_explanation() -> None:
    strategy = AShareTrendStrategy()
    context = StrategyContext(
        security_id="SSE:600001",
        as_of=as_of(),
        data_snapshot_id="snapshot-a-share-001",
        rule_version="rules-cn-v1",
        available_bars=80,
        factors={"momentum.ret_20d.v1": 0.08, "risk.volatility_20d.v1": 0.12},
        metadata={"selected_security_id": "SSE:600001", "trend_score": 0.37},
    )

    signal = strategy.generate_signal(context)
    explanation = strategy.explain(context, signal)

    assert signal.intent is RawSignalIntent.BUY_BIAS
    assert signal.diagnostics["research_status"] == ResearchStatus.RESEARCH.value
    assert explanation.audit_references == ("snapshot-a-share-001", "research.a_share_trend.v1")
    assert strategy.metadata().model_version == "research.a_share_trend.v1"


def test_group_breakdown_supports_year_market_state_and_industry_reports() -> None:
    rows = summarize_group_returns(
        {
            "2026": (0.10, -0.02, 0.03),
            "consumer": (0.04, 0.02),
            "weak_market": (-0.01, -0.03),
        }
    )

    by_group = {row.group: row for row in rows}
    assert by_group["2026"].mean_return == pytest.approx(0.11 / 3)
    assert by_group["2026"].hit_rate == pytest.approx(2 / 3)
    assert by_group["weak_market"].hit_rate == 0.0
