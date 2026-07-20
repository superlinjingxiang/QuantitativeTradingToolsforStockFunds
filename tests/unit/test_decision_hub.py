"""Decision hub tests for TASK-026."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from china_quant_platform.decision import (
    DecisionHub,
    DecisionRequest,
    EvidenceGateStatus,
    ExecutionReadiness,
    ProfitabilityEvidence,
    SimulationEvidence,
    build_research_decision_from_market_data,
)
from china_quant_platform.domain import (
    AbstainReason,
    AnalysisReport,
    AssetType,
    Bar,
    BarInterval,
    Currency,
    DataHealth,
    DataHealthStatus,
    DirectionProbabilities,
    Exchange,
    FinalSignal,
    ForecastValidationEvidence,
    PortfolioStrategyEvidence,
    Quote,
    RecordQualityStatus,
    SecurityRef,
    SecurityStatus,
)


def as_of() -> datetime:
    return datetime(2026, 6, 30, 15, 0, tzinfo=UTC)


def healthy_data() -> DataHealth:
    return DataHealth(status=DataHealthStatus.HEALTHY, block_signal=False, as_of=as_of())


def blocked_data() -> DataHealth:
    return DataHealth(
        status=DataHealthStatus.STALE,
        block_signal=True,
        as_of=as_of(),
        issues=("stale quote",),
    )


def request() -> DecisionRequest:
    return DecisionRequest(security_id="SSE:600519", as_of=as_of())


def analysis(
    final_signal: FinalSignal = FinalSignal.BUY_CANDIDATE,
    *,
    forecast_validation: ForecastValidationEvidence | None = None,
) -> AnalysisReport:
    return AnalysisReport(
        security_id="SSE:600519",
        as_of=as_of(),
        data_health=healthy_data() if final_signal is not FinalSignal.ABSTAIN else blocked_data(),
        strategy_id="strategy.demo",
        strategy_version="v1",
        horizon=5,
        market_regime="TREND_UP",
        direction_probabilities=DirectionProbabilities(up=0.62, flat=0.23, down=0.15),
        raw_signal="BUY_BIAS" if final_signal is not FinalSignal.ABSTAIN else "ABSTAIN",
        final_signal=final_signal,
        valid_until=as_of() + timedelta(days=1),
        positive_drivers=("momentum supports candidate",),
        negative_drivers=("volatility still limits position",),
        model_version="forecast-v1",
        rule_version="rules-cn-v1",
        data_snapshot_id="snapshot-001",
        expected_return_quantiles={"p05": -0.02, "p50": 0.03, "p95": 0.08},
        expected_drawdown=-0.04,
        forecast_validation=forecast_validation,
        grade="B",
        target_position_limit=0.05,
        exit_or_invalidation_conditions=("trend break",),
        abstain_reason=None if final_signal is not FinalSignal.ABSTAIN else AbstainReason.DATA,
    )


def profitability() -> ProfitabilityEvidence:
    return ProfitabilityEvidence(
        source="fixture",
        strategy_id="strategy.demo",
        strategy_version="v1",
        total_return=0.18,
        annualized_return=0.12,
        max_drawdown=-0.08,
        benchmark_total_return=0.05,
        excess_return=0.13,
        trade_count=24,
        turnover=5.2,
        cost_drag=0.012,
        stress_round_trip_cost_bps=45.0,
        stress_total_return=0.15,
        stress_max_drawdown=-0.09,
        cost_stress_passed=True,
        calibration_sample_count=80,
        brier_score=0.18,
        checksum="profitability-fixture",
    )


def simulation() -> SimulationEvidence:
    return SimulationEvidence(
        account_id="paper-main",
        net_asset_value=105_000,
        realized_pnl=2_000,
        unrealized_pnl=3_000,
        order_count=12,
        execution_count=12,
        deviation_count=12,
        threshold_breach_count=0,
        max_abs_slippage_pct=0.002,
        checksum="simulation-fixture",
    )


def forecast_validation() -> ForecastValidationEvidence:
    return ForecastValidationEvidence(
        sample_count=60,
        required_sample_count=40,
        candidate_count=1260,
        evaluation_stride=21,
        training_embargo=21,
        interval_coverage=0.82,
        downside_breach_rate=0.08,
        direction_brier_score=0.19,
    )


def portfolio_evidence(
    *,
    validation_status: str = "PASS",
    selected: bool = True,
    stale: bool = False,
    capacity_status: str = "PASS",
) -> PortfolioStrategyEvidence:
    selected_ids = ("SSE:600519", "SSE:510300") if selected else ("SSE:510300",)
    return PortfolioStrategyEvidence(
        security_id="SSE:600519",
        strategy_id="strategy.etf_rotation_portfolio",
        strategy_version="etf-rotation-v9",
        validation_status=validation_status,
        as_of_date=date(2026, 6, 30),
        signal_date=date(2026, 6, 27),
        execution_date=date(2026, 6, 30),
        selected_security_ids=selected_ids,
        current_security_selected=selected,
        current_security_rank=1 if selected else 3,
        current_security_momentum=0.12,
        target_position_fraction=0.80,
        current_security_target_fraction=0.40 if selected else 0.0,
        bars_until_next_rebalance=18,
        base_total_return=0.42,
        stress_total_return=0.35,
        excess_return=0.11,
        max_drawdown=-0.12,
        sharpe_ratio=1.02,
        walk_forward_fold_count=1 if validation_status == "WATCH" else 3,
        required_walk_forward_fold_count=3,
        walk_forward_positive_ratio=1.0,
        walk_forward_excess_ratio=0.67,
        trading_system="T+1",
        capacity_status=capacity_status,
        capacity_reference_capital=100_000,
        capacity_max_participation_rate=0.008,
        capacity_estimated_round_trip_cost_bps=25.7,
        capacity_max_supported_capital=250_000,
        capacity_observation_count=12,
        stale=stale,
        notes=("fixture",),
    )


def security() -> SecurityRef:
    return SecurityRef(
        security_id="SSE:600519",
        symbol="600519",
        name="贵州茅台",
        asset_type=AssetType.STOCK,
        exchange=Exchange.SSE,
        currency=Currency.CNY,
        listed_date=date(2001, 8, 27),
        status_date=date(2026, 6, 30),
        status=SecurityStatus.ACTIVE,
    )


def quote() -> Quote:
    now = as_of()
    return Quote(
        security_id="SSE:600519",
        latest_price=126.0,
        previous_close=124.0,
        open_price=124.5,
        high_price=127.0,
        low_price=123.5,
        volume=10_000,
        amount=1_260_000,
        provider="fixture",
        schema_version="fixture.v1",
        source_time=now,
        observed_at=now,
        received_at=now,
        quality_status=RecordQualityStatus.OK,
    )


def bars(count: int = 90) -> tuple[Bar, ...]:
    output: list[Bar] = []
    start = date(2026, 1, 2)
    trading_index = 0
    current_day = start
    while len(output) < count:
        if current_day.weekday() < 5:
            close = 100.0 + trading_index * 0.45 + (trading_index % 7) * 0.08
            start_time = datetime.combine(current_day, time(9, 30), tzinfo=UTC)
            end_time = datetime.combine(current_day, time(15, 0), tzinfo=UTC)
            output.append(
                Bar(
                    security_id="SSE:600519",
                    interval=BarInterval.DAILY,
                    start_time=start_time,
                    end_time=end_time,
                    trade_date=current_day,
                    open_price=close - 0.4,
                    high_price=close + 0.9,
                    low_price=close - 0.8,
                    close_price=close,
                    volume=100_000 + trading_index,
                    amount=close * 100_000,
                    provider="fixture",
                    schema_version="fixture.v1",
                    source_time=end_time,
                    observed_at=end_time,
                    received_at=end_time,
                    quality_status=RecordQualityStatus.OK,
                )
            )
            trading_index += 1
        current_day += timedelta(days=1)
    return tuple(output)


def test_missing_evidence_downgrades_tradeable_signal_to_watch() -> None:
    report = DecisionHub().build_report(request=request(), analysis_report=analysis())

    assert report.final_signal is FinalSignal.WATCH
    assert report.execution_readiness is ExecutionReadiness.RESEARCH_ONLY
    assert any(gate.status is EvidenceGateStatus.MISSING for gate in report.gates)
    assert report.target_position_limit == 0.0
    assert report.real_order_submission_enabled is False
    assert "不保证盈利" in report.no_profit_guarantee


def test_all_evidence_passes_to_api_candidate_without_real_order_path() -> None:
    report = DecisionHub().build_report(
        request=request(),
        analysis_report=analysis(),
        profitability=profitability(),
        simulation=simulation(),
    )

    assert report.final_signal is FinalSignal.BUY_CANDIDATE
    assert report.execution_readiness is ExecutionReadiness.API_CANDIDATE
    assert all(gate.status is EvidenceGateStatus.PASS for gate in report.gates)
    assert report.target_position_limit == 0.05
    assert report.real_order_submission_enabled is False


def test_watch_portfolio_evidence_blocks_new_position_upgrade() -> None:
    report = DecisionHub().build_report(
        request=request(),
        analysis_report=analysis().model_copy(
            update={"portfolio_strategy_evidence": portfolio_evidence(validation_status="WATCH")}
        ),
        profitability=profitability(),
        simulation=simulation(),
    )

    gate = next(item for item in report.gates if item.gate_id == "portfolio-strategy")
    assert gate.status is EvidenceGateStatus.WARN
    assert report.final_signal is FinalSignal.WATCH
    assert report.target_position_limit == 0.0
    assert any("新增仓位许可" in reason for reason in gate.reasons)


def test_unselected_security_is_not_treated_as_portfolio_buy_candidate() -> None:
    report = DecisionHub().build_report(
        request=request(),
        analysis_report=analysis().model_copy(
            update={"portfolio_strategy_evidence": portfolio_evidence(selected=False)}
        ),
        profitability=profitability(),
        simulation=simulation(),
    )

    gate = next(item for item in report.gates if item.gate_id == "portfolio-strategy")
    assert gate.status is EvidenceGateStatus.WARN
    assert report.final_signal is FinalSignal.WATCH
    assert "未进入" in gate.reasons[0]


def test_missing_capacity_evidence_fails_closed() -> None:
    evidence = portfolio_evidence(capacity_status="MISSING").model_copy(
        update={
            "capacity_reference_capital": None,
            "capacity_max_participation_rate": None,
            "capacity_estimated_round_trip_cost_bps": None,
            "capacity_max_supported_capital": None,
            "capacity_observation_count": 0,
            "capacity_missing_observation_count": 2,
        }
    )
    report = DecisionHub().build_report(
        request=request(),
        analysis_report=analysis().model_copy(update={"portfolio_strategy_evidence": evidence}),
        profitability=profitability(),
        simulation=simulation(),
    )

    gate = next(item for item in report.gates if item.gate_id == "portfolio-strategy")
    assert gate.status is EvidenceGateStatus.MISSING
    assert report.final_signal is FinalSignal.WATCH
    assert "2笔调仓" in gate.reasons[0]


def test_failed_capacity_blocks_portfolio_candidate() -> None:
    report = DecisionHub().build_report(
        request=request(),
        analysis_report=analysis().model_copy(
            update={
                "portfolio_strategy_evidence": portfolio_evidence(
                    capacity_status="FAIL"
                ).model_copy(
                    update={
                        "capacity_max_participation_rate": 0.08,
                        "capacity_estimated_round_trip_cost_bps": 49.0,
                    }
                )
            }
        ),
        profitability=profitability(),
        simulation=simulation(),
    )

    gate = next(item for item in report.gates if item.gate_id == "portfolio-strategy")
    assert gate.status is EvidenceGateStatus.FAIL
    assert report.final_signal is FinalSignal.WATCH
    assert "8.00%" in gate.reasons[0]


def test_watch_capacity_requires_paper_fill_confirmation() -> None:
    report = DecisionHub().build_report(
        request=request(),
        analysis_report=analysis().model_copy(
            update={
                "portfolio_strategy_evidence": portfolio_evidence(
                    capacity_status="WATCH"
                ).model_copy(update={"capacity_max_participation_rate": 0.03})
            }
        ),
        profitability=profitability(),
        simulation=simulation(),
    )

    gate = next(item for item in report.gates if item.gate_id == "portfolio-strategy")
    assert gate.status is EvidenceGateStatus.WARN
    assert report.final_signal is FinalSignal.WATCH
    assert any("容量WATCH" in reason for reason in gate.reasons)


def test_purged_forecast_calibration_is_included_in_decision_gate() -> None:
    report = DecisionHub().build_report(
        request=request(),
        analysis_report=analysis(forecast_validation=forecast_validation()),
        profitability=profitability(),
        simulation=simulation(),
    )

    gate = next(item for item in report.gates if item.gate_id == "calibration")
    assert gate.status is EvidenceGateStatus.PASS
    assert "清除持有期重叠" in gate.reasons[0]


def test_insufficient_independent_forecast_samples_block_execution_upgrade() -> None:
    evidence = forecast_validation().model_copy(update={"sample_count": 20})

    report = DecisionHub().build_report(
        request=request(),
        analysis_report=analysis(forecast_validation=evidence),
        profitability=profitability(),
        simulation=simulation(),
    )

    gate = next(item for item in report.gates if item.gate_id == "calibration")
    assert gate.status is EvidenceGateStatus.MISSING
    assert "20/40" in gate.reasons[0]
    assert report.final_signal is FinalSignal.WATCH


def test_overlapping_forecast_calibration_fails_evidence_gate() -> None:
    evidence = forecast_validation().model_copy(
        update={"evaluation_stride": 1, "training_embargo": 0}
    )

    report = DecisionHub().build_report(
        request=request(),
        analysis_report=analysis(forecast_validation=evidence),
        profitability=profitability(),
        simulation=simulation(),
    )

    gate = next(item for item in report.gates if item.gate_id == "calibration")
    assert gate.status is EvidenceGateStatus.FAIL
    assert any("重叠" in reason for reason in gate.reasons)
    assert report.final_signal is FinalSignal.WATCH


def test_risk_adjusted_benchmark_path_can_pass_without_positive_excess() -> None:
    evidence = profitability().model_copy(
        update={
            "total_return": 0.20,
            "excess_return": -0.03,
            "max_drawdown": -0.10,
            "benchmark_max_drawdown": -0.25,
            "sharpe_ratio": 1.05,
        }
    )

    report = DecisionHub().build_report(
        request=request(),
        analysis_report=analysis(),
        profitability=evidence,
        simulation=simulation(),
    )

    assert report.final_signal is FinalSignal.BUY_CANDIDATE
    profitability_gate = next(
        gate for gate in report.gates if gate.gate_id == "profitability-evidence"
    )
    assert profitability_gate.status is EvidenceGateStatus.PASS


def test_negative_excess_without_drawdown_improvement_fails_profitability_gate() -> None:
    evidence = profitability().model_copy(
        update={
            "total_return": 0.20,
            "excess_return": -0.03,
            "max_drawdown": -0.22,
            "benchmark_max_drawdown": -0.25,
            "sharpe_ratio": 1.05,
        }
    )

    report = DecisionHub().build_report(
        request=request(),
        analysis_report=analysis(),
        profitability=evidence,
        simulation=simulation(),
    )

    assert report.final_signal is FinalSignal.WATCH
    profitability_gate = next(
        gate for gate in report.gates if gate.gate_id == "profitability-evidence"
    )
    assert profitability_gate.status is EvidenceGateStatus.FAIL


def test_missing_cost_stress_is_visible_and_blocks_execution_upgrade() -> None:
    evidence = profitability().model_copy(update={"cost_stress_passed": None})

    report = DecisionHub().build_report(
        request=request(),
        analysis_report=analysis(),
        profitability=evidence,
        simulation=simulation(),
    )

    gate = next(item for item in report.gates if item.gate_id == "cost-stress")
    assert gate.status is EvidenceGateStatus.MISSING
    assert report.final_signal is FinalSignal.WATCH
    assert report.execution_readiness is ExecutionReadiness.RESEARCH_ONLY


def test_failed_cost_stress_is_a_real_blocking_gate() -> None:
    evidence = profitability().model_copy(
        update={"stress_total_return": -0.01, "cost_stress_passed": False}
    )

    report = DecisionHub().build_report(
        request=request(),
        analysis_report=analysis(),
        profitability=evidence,
        simulation=simulation(),
    )

    gate = next(item for item in report.gates if item.gate_id == "cost-stress")
    assert gate.status is EvidenceGateStatus.FAIL
    assert report.final_signal is FinalSignal.WATCH


def test_blocked_data_forces_abstain_even_when_other_evidence_exists() -> None:
    report = DecisionHub().build_report(
        request=request(),
        analysis_report=analysis(FinalSignal.ABSTAIN),
        profitability=profitability(),
        simulation=simulation(),
    )

    assert report.final_signal is FinalSignal.ABSTAIN
    assert report.execution_readiness is ExecutionReadiness.NOT_ELIGIBLE
    assert any("stale quote" in reason for gate in report.gates for reason in gate.reasons)


def test_research_decision_from_market_data_contains_profitability_context() -> None:
    report = build_research_decision_from_market_data(
        security=security(),
        bars=bars(),
        quote=quote(),
        data_health=healthy_data(),
    )

    assert report.analysis_report.security_id == "SSE:600519"
    assert report.profitability is not None
    assert report.profitability.trade_count > 0
    assert report.simulation is None
    assert report.final_signal in {FinalSignal.WATCH, FinalSignal.BUY_CANDIDATE}
    assert any("模拟盘" in item for item in report.negative_evidence)
    cost_gate = next(gate for gate in report.gates if gate.gate_id == "cost-stress")
    assert cost_gate.status is EvidenceGateStatus.MISSING
