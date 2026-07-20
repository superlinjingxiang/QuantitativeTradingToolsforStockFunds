"""Schema and model round-trip tests for TASK-002 contracts."""

from __future__ import annotations

import copy
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema.validators import Draft202012Validator
from pydantic import ValidationError

from china_quant_platform.domain import (
    AbstainReason,
    AnalysisReport,
    AssetType,
    BacktestConfig,
    DataHealth,
    DataHealthStatus,
    DirectionProbabilities,
    Exchange,
    FinalSignal,
    ForecastValidationEvidence,
    PortfolioStrategyEvidence,
    RuleReviewStatus,
    SecurityRule,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DIR = PROJECT_ROOT / "spec" / "contracts"


def load_schema(name: str) -> dict[str, Any]:
    schema = json.loads((CONTRACT_DIR / name).read_text(encoding="utf-8"))
    return cast(dict[str, Any], schema)


def schema_for_analysis_report() -> dict[str, Any]:
    schema = copy.deepcopy(load_schema("analysis_report.schema.json"))
    schema["properties"]["data_health"] = load_schema("data-health.schema.json")
    return schema


def assert_valid(schema_name: str, payload: dict[str, Any]) -> None:
    schema = load_schema(schema_name)
    Draft202012Validator(schema).validate(payload)


def aware_datetime(hour: int = 15, minute: int = 0) -> datetime:
    return datetime(2026, 6, 28, hour, minute, tzinfo=UTC)


def valid_health() -> DataHealth:
    return DataHealth(
        status=DataHealthStatus.HEALTHY,
        block_signal=False,
        as_of=aware_datetime(),
        issues=(),
    )


def valid_tradeable_report() -> AnalysisReport:
    return AnalysisReport(
        security_id="SSE:600519",
        as_of=aware_datetime(),
        data_health=valid_health(),
        strategy_id="strategy.multi_factor",
        strategy_version="1.0.0",
        horizon=5,
        market_regime="neutral",
        direction_probabilities=DirectionProbabilities(up=0.6, flat=0.3, down=0.1),
        raw_signal="BUY_CANDIDATE",
        final_signal=FinalSignal.BUY_CANDIDATE,
        valid_until=aware_datetime(15, 30),
        positive_drivers=("momentum",),
        negative_drivers=("liquidity risk",),
        model_version="model.v1",
        rule_version="rules.2026",
        data_snapshot_id="snapshot.20260628",
        expected_return_quantiles={"p05": -0.02, "p50": 0.01, "p95": 0.05},
        expected_drawdown=0.03,
        forecast_validation=ForecastValidationEvidence(
            sample_count=60,
            required_sample_count=40,
            candidate_count=1260,
            evaluation_stride=21,
            training_embargo=21,
            interval_coverage=0.82,
            downside_breach_rate=0.08,
            direction_brier_score=0.19,
        ),
        portfolio_strategy_evidence=PortfolioStrategyEvidence(
            security_id="SSE:600519",
            strategy_id="strategy.etf_rotation",
            strategy_version="etf-rotation-v10",
            validation_status="WATCH",
            as_of_date=date(2026, 6, 28),
            signal_date=date(2026, 6, 26),
            execution_date=date(2026, 6, 27),
            selected_security_ids=("SSE:600519", "SSE:510300"),
            current_security_selected=True,
            current_security_rank=1,
            current_security_momentum=0.12,
            target_position_fraction=0.5,
            current_security_target_fraction=0.25,
            bars_until_next_rebalance=20,
            base_total_return=0.2,
            stress_total_return=0.15,
            excess_return=0.05,
            max_drawdown=-0.1,
            sharpe_ratio=1.0,
            walk_forward_fold_count=1,
            required_walk_forward_fold_count=3,
            walk_forward_positive_ratio=1.0,
            walk_forward_excess_ratio=1.0,
            cumulative_turnover=6.68,
            average_rebalance_turnover=0.41,
            cumulative_transaction_cost=0.0064,
            trading_system="T+1",
            capacity_status="PASS",
            capacity_model_version="etf-capacity-impact-v2",
            capacity_reference_capital=100_000,
            capacity_max_participation_rate=0.008,
            capacity_estimated_round_trip_cost_bps=25.7,
            capacity_max_supported_capital=250_000,
            capacity_observation_count=12,
            notes=("research_only",),
        ),
        grade="B",
        target_position_limit=0.05,
        exit_or_invalidation_conditions=("trend break",),
    )


def test_data_health_round_trips_through_schema() -> None:
    health = valid_health()
    payload = health.to_contract_dict()

    assert_valid("data-health.schema.json", payload)
    assert DataHealth.from_contract_dict(payload) == health


def test_analysis_report_round_trips_through_schema() -> None:
    report = valid_tradeable_report()
    payload = report.to_contract_dict()

    Draft202012Validator(schema_for_analysis_report()).validate(payload)
    assert AnalysisReport.from_contract_dict(payload) == report


def test_backtest_config_round_trips_through_schema() -> None:
    config = BacktestConfig(
        strategy_id="strategy.multi_factor",
        strategy_version="1.0.0",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 28),
        initial_cash=1_000_000,
        data_snapshot_id="snapshot.20260628",
        rule_version="rules.2026",
        seed=42,
        universe_id="csi300",
        benchmark_id="000300.SH",
        parameters={"max_position": 0.05},
    )
    payload = config.to_contract_dict()

    assert_valid("backtest-config.schema.json", payload)
    assert BacktestConfig.from_contract_dict(payload) == config


def test_security_rule_round_trips_through_schema_with_extra_fields() -> None:
    rule = SecurityRule.model_validate(
        {
            "rule_id": "sse.stock.2026",
            "version": "rules.2026",
            "exchange": Exchange.SSE,
            "asset_type": AssetType.STOCK,
            "effective_from": date(2026, 1, 1),
            "source": "SSE rule fixture",
            "review_status": RuleReviewStatus.APPROVED,
            "lot_size": 100,
            "tick_size": 0.01,
            "intraday_round_trip": False,
            "board": "MAIN",
        }
    )
    payload = rule.to_contract_dict()

    assert_valid("security-rule.schema.json", payload)
    assert SecurityRule.from_contract_dict(payload).to_contract_dict() == payload


def test_report_rejects_invalid_probability_values() -> None:
    payload = valid_tradeable_report().to_contract_dict()
    payload["direction_probabilities"] = {"up": 0.8, "flat": 0.1, "down": 0.2}

    with pytest.raises(ValidationError):
        AnalysisReport.from_contract_dict(payload)


def test_tradeable_report_rejects_missing_source_versions() -> None:
    with pytest.raises(ValidationError):
        AnalysisReport(
            **{
                **valid_tradeable_report().to_contract_dict(),
                "model_version": "",
            }
        )


def test_tradeable_report_rejects_blocked_data_health() -> None:
    payload = valid_tradeable_report().to_contract_dict()
    payload["data_health"] = DataHealth(
        status=DataHealthStatus.STALE,
        block_signal=True,
        as_of=aware_datetime(),
        issues=("stale quote",),
    ).to_contract_dict()

    with pytest.raises(ValidationError):
        AnalysisReport.from_contract_dict(payload)


def test_abstain_report_requires_typed_reason() -> None:
    payload = valid_tradeable_report().to_contract_dict()
    payload["final_signal"] = FinalSignal.ABSTAIN.value
    payload["abstain_reason"] = None

    with pytest.raises(ValidationError):
        AnalysisReport.from_contract_dict(payload)

    payload["abstain_reason"] = AbstainReason.DATA.value
    report = AnalysisReport.from_contract_dict(payload)
    assert report.final_signal is FinalSignal.ABSTAIN
    assert report.abstain_reason is AbstainReason.DATA
