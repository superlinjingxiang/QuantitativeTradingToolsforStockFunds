"""ETF rotation baseline strategy tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from china_quant_platform.strategies import (
    EtfRotationConfig,
    EtfRotationStrategy,
    EtfSignalFeatures,
    EtfUniverseMember,
    RawSignalIntent,
    ResearchStatus,
    StrategyContext,
    cost_turnover_sensitivity,
)


def as_of() -> datetime:
    return datetime(2026, 1, 31, 15, 0, tzinfo=UTC)


def member(
    security_id: str,
    *,
    liquidity_score: float = 0.9,
    approved: bool = True,
    listed: bool = True,
    bucket: str = "broad",
) -> EtfUniverseMember:
    return EtfUniverseMember(
        security_id=security_id,
        name=security_id,
        as_of=as_of(),
        approved=approved,
        listed=listed,
        liquidity_score=liquidity_score,
        asset_bucket=bucket,
    )


def test_etf_rotation_ranks_point_in_time_universe_and_rejects_bad_members() -> None:
    strategy = EtfRotationStrategy(
        EtfRotationConfig(
            max_positions=2,
            max_volatility=0.25,
            min_liquidity_score=0.5,
            target_gross_exposure=0.8,
        )
    )
    members = (
        member("ETF:broad"),
        member("ETF:bond", bucket="bond"),
        member("ETF:theme"),
        member("ETF:illiquid", liquidity_score=0.2),
    )
    features = {
        "ETF:broad": EtfSignalFeatures(
            momentum=0.08,
            absolute_momentum=0.06,
            trend_strength=0.7,
            volatility=0.12,
            average_correlation=0.2,
        ),
        "ETF:bond": EtfSignalFeatures(
            momentum=0.04,
            absolute_momentum=0.03,
            trend_strength=0.5,
            volatility=0.04,
            average_correlation=0.1,
        ),
        "ETF:theme": EtfSignalFeatures(
            momentum=0.10,
            absolute_momentum=0.08,
            trend_strength=0.6,
            volatility=0.35,
            average_correlation=0.2,
        ),
    }

    selection = strategy.rank_universe(members=members, features=features)

    assert selection.research_status is ResearchStatus.RESEARCH
    assert tuple(score.security_id for score in selection.selected) == ("ETF:broad", "ETF:bond")
    assert selection.selected[0].target_weight == pytest.approx(0.4)
    assert selection.selected[0].cash_weight == pytest.approx(0.2)
    assert selection.rejected["ETF:theme"] == ("volatility_above_threshold",)
    assert selection.rejected["ETF:illiquid"] == (
        "liquidity_below_threshold",
        "missing_features",
    )


def test_etf_rotation_strategy_emits_raw_signal_and_explanation_only() -> None:
    strategy = EtfRotationStrategy()
    context = StrategyContext(
        security_id="ETF:broad",
        as_of=as_of(),
        data_snapshot_id="snapshot-etf-001",
        rule_version="rules-cn-v1",
        available_bars=80,
        factors={"momentum.ret_20d.v1": 0.08, "risk.volatility_20d.v1": 0.12},
        metadata={"selected_security_id": "ETF:broad", "rotation_score": 0.42},
    )

    signal = strategy.generate_signal(context)
    explanation = strategy.explain(context, signal)
    metadata = strategy.metadata()

    assert signal.intent is RawSignalIntent.BUY_BIAS
    assert signal.requires_rule_gate is True
    assert signal.diagnostics["research_status"] == ResearchStatus.RESEARCH.value
    assert explanation.audit_references == ("snapshot-etf-001", "research.etf_rotation.v1")
    assert metadata.model_version == "research.etf_rotation.v1"
    assert metadata.name == "ETF medium-term rotation baseline"


def test_etf_rotation_strategy_abstains_when_no_selection_exists() -> None:
    strategy = EtfRotationStrategy()
    context = StrategyContext(
        security_id="ETF:broad",
        as_of=as_of(),
        data_snapshot_id="snapshot-etf-001",
        rule_version="rules-cn-v1",
        available_bars=80,
    )

    signal = strategy.generate_signal(context)

    assert signal.intent is RawSignalIntent.ABSTAIN


def test_cost_turnover_sensitivity_estimates_net_return() -> None:
    scenarios = cost_turnover_sensitivity(
        gross_return=0.10,
        turnovers=(0.5, 1.0),
        cost_bps_values=(20.0,),
    )

    assert tuple(scenario.scenario_id for scenario in scenarios) == (
        "turnover-0.5-cost-20bps",
        "turnover-1-cost-20bps",
    )
    assert scenarios[0].net_return == pytest.approx(0.099)
    assert scenarios[1].net_return == pytest.approx(0.098)
