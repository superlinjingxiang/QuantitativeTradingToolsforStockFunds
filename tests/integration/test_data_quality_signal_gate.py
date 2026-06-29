"""Signal blocking integration tests for data quality gates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from china_quant_platform.data import DataQualityPolicy, DataQualityService
from china_quant_platform.domain import (
    AbstainReason,
    AnalysisReport,
    DataHealth,
    DirectionProbabilities,
    FinalSignal,
    Quote,
    RecordQualityStatus,
)


def aware_datetime(hour: int = 15, minute: int = 0) -> datetime:
    return datetime(2026, 6, 22, hour, minute, tzinfo=UTC)


def make_quote() -> Quote:
    source_time = aware_datetime(14, 59)
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


def report_payload(data_health: DataHealth, final_signal: FinalSignal) -> dict[str, object]:
    return {
        "security_id": "SSE:600519",
        "as_of": aware_datetime(),
        "data_health": data_health,
        "strategy_id": "fixture_strategy",
        "strategy_version": "1.0.0",
        "horizon": 5,
        "market_regime": "fixture",
        "direction_probabilities": DirectionProbabilities(up=0.2, flat=0.7, down=0.1),
        "raw_signal": "neutral",
        "final_signal": final_signal,
        "valid_until": aware_datetime() + timedelta(minutes=30),
        "positive_drivers": ("trend intact",),
        "negative_drivers": ("data risk",),
        "model_version": "model.v1",
        "rule_version": "rules.v1",
        "data_snapshot_id": "snapshot.v1",
        "expected_return_quantiles": {"p50": 0.0},
        "exit_or_invalidation_conditions": ("data becomes stale",),
    }


def blocked_data_health() -> DataHealth:
    service = DataQualityService(DataQualityPolicy(quote_stale_after=timedelta(seconds=5)))
    quote = make_quote()
    return service.evaluate_quote(
        quote,
        as_of=quote.source_time + timedelta(seconds=6),
    ).health


def test_blocked_data_health_cannot_be_wrapped_as_tradeable_report() -> None:
    payload = report_payload(blocked_data_health(), FinalSignal.HOLD)

    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)


def test_blocked_data_health_can_be_reported_as_abstain() -> None:
    payload = report_payload(blocked_data_health(), FinalSignal.ABSTAIN)
    payload["positive_drivers"] = ()
    payload["negative_drivers"] = ()
    payload["exit_or_invalidation_conditions"] = ()
    payload["abstain_reason"] = AbstainReason.DATA

    report = AnalysisReport.model_validate(payload)

    assert report.final_signal is FinalSignal.ABSTAIN
    assert report.data_health.block_signal is True
    assert report.abstain_reason is AbstainReason.DATA
