"""Decision hub service for strategy advice and evidence gates."""

from __future__ import annotations

from math import isfinite

from china_quant_platform.decision.models import (
    TRADEABLE_DECISION_SIGNALS,
    DecisionReport,
    DecisionRequest,
    EvidenceGate,
    EvidenceGateStatus,
    ExecutionReadiness,
    ProfitabilityEvidence,
    SimulationEvidence,
)
from china_quant_platform.domain import AnalysisReport, FinalSignal
from china_quant_platform.reporting import BacktestReport
from china_quant_platform.simulation import (
    REAL_ORDER_SUBMISSION_ENABLED,
    SimulationAccountState,
    simulation_state_checksum,
)


class DecisionHub:
    """Combine analysis, profitability evidence, paper evidence, and gates."""

    def build_report(
        self,
        *,
        request: DecisionRequest,
        analysis_report: AnalysisReport,
        profitability: ProfitabilityEvidence | None = None,
        backtest_report: BacktestReport | None = None,
        benchmark_total_return: float | None = None,
        simulation: SimulationEvidence | None = None,
        simulation_state: SimulationAccountState | None = None,
        cost_stress_passed: bool = True,
        out_of_sample_passed: bool = True,
    ) -> DecisionReport:
        if profitability is None and backtest_report is not None:
            profitability = profitability_from_backtest(
                backtest_report,
                benchmark_total_return=benchmark_total_return,
            )
        if simulation is None and simulation_state is not None:
            simulation = simulation_evidence_from_state(simulation_state)

        gates = (
            _data_gate(analysis_report),
            _analysis_gate(analysis_report),
            _profitability_gate(request, profitability, out_of_sample_passed),
            _calibration_gate(request, profitability),
            _cost_stress_gate(cost_stress_passed),
            _simulation_gate(request, simulation),
            _real_order_gate(),
        )
        final_signal = _decision_signal(analysis_report.final_signal, gates)
        readiness = _execution_readiness(
            analysis_report=analysis_report,
            final_signal=final_signal,
            gates=gates,
            request=request,
        )
        confidence = _decision_confidence(analysis_report, gates)
        target_position_limit = (
            analysis_report.target_position_limit
            if final_signal in TRADEABLE_DECISION_SIGNALS
            else 0.0
        )
        return DecisionReport(
            request=request,
            analysis_report=analysis_report,
            final_signal=final_signal,
            execution_readiness=readiness,
            confidence=confidence,
            target_position_limit=target_position_limit,
            valid_until=analysis_report.valid_until,
            profitability=profitability,
            simulation=simulation,
            gates=gates,
            positive_evidence=_positive_evidence(analysis_report, profitability, simulation),
            negative_evidence=_negative_evidence(gates, analysis_report, profitability, simulation),
            caveats=_caveats(final_signal, readiness),
        )


def profitability_from_backtest(
    report: BacktestReport,
    *,
    benchmark_total_return: float | None = None,
) -> ProfitabilityEvidence:
    total_return = report.performance.total_return
    excess_return = (
        None if benchmark_total_return is None else total_return - benchmark_total_return
    )
    return ProfitabilityEvidence(
        source="backtest_report",
        strategy_id=report.manifest.strategy_id,
        strategy_version=report.manifest.strategy_version,
        total_return=total_return,
        annualized_return=report.performance.annualized_return,
        max_drawdown=report.performance.max_drawdown,
        benchmark_total_return=benchmark_total_return,
        excess_return=excess_return,
        trade_count=len(report.trades),
        turnover=report.costs.turnover,
        cost_drag=report.costs.total_fees + report.costs.slippage_cost + report.costs.spread_cost,
        calibration_sample_count=report.calibration.sample_count,
        brier_score=report.calibration.brier_score,
        checksum=report.checksum,
        notes=("Backtest report is deterministic and includes transaction costs.",),
    )


def simulation_evidence_from_state(state: SimulationAccountState) -> SimulationEvidence:
    max_abs_slippage = _max_abs_slippage(state)
    threshold_breaches = sum(1 for deviation in state.deviations if deviation.threshold_breached)
    metrics = state.metrics
    return SimulationEvidence(
        account_id=state.account_id,
        net_asset_value=metrics.net_asset_value,
        realized_pnl=metrics.realized_pnl,
        unrealized_pnl=metrics.unrealized_pnl,
        order_count=len(state.orders),
        execution_count=len(state.executions),
        deviation_count=len(state.deviations),
        threshold_breach_count=threshold_breaches,
        max_abs_slippage_pct=max_abs_slippage,
        checksum=simulation_state_checksum(state),
        notes=("Paper broker evidence only; real order submission remains disabled.",),
    )


def _data_gate(analysis_report: AnalysisReport) -> EvidenceGate:
    if analysis_report.data_health.block_signal:
        issues = analysis_report.data_health.issues or (analysis_report.data_health.status.value,)
        return EvidenceGate(
            gate_id="data-health",
            name="数据健康",
            status=EvidenceGateStatus.FAIL,
            reasons=tuple(f"数据阻断：{issue}" for issue in issues),
        )
    return EvidenceGate(
        gate_id="data-health",
        name="数据健康",
        status=EvidenceGateStatus.PASS,
        reasons=("当前数据未阻断策略计算。",),
    )


def _analysis_gate(analysis_report: AnalysisReport) -> EvidenceGate:
    if analysis_report.final_signal is FinalSignal.ABSTAIN:
        reason = (
            analysis_report.abstain_reason.value
            if analysis_report.abstain_reason is not None
            else "UNKNOWN"
        )
        return EvidenceGate(
            gate_id="analysis-signal",
            name="策略与预测",
            status=EvidenceGateStatus.FAIL,
            reasons=(f"分析报告已输出ABSTAIN：{reason}",),
        )
    return EvidenceGate(
        gate_id="analysis-signal",
        name="策略与预测",
        status=EvidenceGateStatus.PASS,
        reasons=(f"分析报告输出原始最终信号：{analysis_report.final_signal.value}",),
    )


def _profitability_gate(
    request: DecisionRequest,
    profitability: ProfitabilityEvidence | None,
    out_of_sample_passed: bool,
) -> EvidenceGate:
    if profitability is None:
        return EvidenceGate(
            gate_id="profitability-evidence",
            name="历史赚钱证据",
            status=EvidenceGateStatus.MISSING,
            reasons=("缺少回测或样本外收益证据。",),
        )

    reasons: list[str] = []
    if not out_of_sample_passed:
        reasons.append("样本外或滚动验证未通过。")
    if profitability.total_return is None or profitability.total_return <= 0:
        reasons.append("扣除成本后的历史净收益未为正。")
    if profitability.trade_count < request.min_backtest_trades:
        reasons.append(f"交易次数不足：{profitability.trade_count}/{request.min_backtest_trades}。")
    if profitability.max_drawdown is None:
        reasons.append("缺少最大回撤证据。")
    elif abs(profitability.max_drawdown) > request.max_backtest_drawdown:
        reasons.append(
            f"最大回撤超出门槛：{abs(profitability.max_drawdown):.2%}/"
            f"{request.max_backtest_drawdown:.2%}。"
        )
    if not profitability.has_benchmark_comparison:
        reasons.append("缺少基准比较，不能证明相对优势。")
    elif profitability.excess_return is not None and profitability.excess_return <= 0:
        if not _risk_adjusted_benchmark_passed(request, profitability):
            reasons.append("相对基准超额未为正，风险调整收益或回撤改善也未通过。")

    if reasons:
        return EvidenceGate(
            gate_id="profitability-evidence",
            name="历史赚钱证据",
            status=EvidenceGateStatus.FAIL,
            reasons=tuple(reasons),
        )
    return EvidenceGate(
        gate_id="profitability-evidence",
        name="历史赚钱证据",
        status=EvidenceGateStatus.PASS,
        reasons=("扣除成本后的收益、回撤、交易次数和基准/风险调整比较通过。",),
    )


def _risk_adjusted_benchmark_passed(
    request: DecisionRequest,
    profitability: ProfitabilityEvidence,
) -> bool:
    if (
        profitability.total_return is None
        or profitability.total_return <= 0
        or profitability.sharpe_ratio is None
        or profitability.sharpe_ratio < request.min_sharpe_ratio
        or profitability.max_drawdown is None
        or profitability.benchmark_max_drawdown is None
        or profitability.benchmark_max_drawdown >= 0
    ):
        return False
    return abs(profitability.max_drawdown) <= abs(profitability.benchmark_max_drawdown) * (
        1.0 - request.min_drawdown_improvement
    )


def _calibration_gate(
    request: DecisionRequest,
    profitability: ProfitabilityEvidence | None,
) -> EvidenceGate:
    if profitability is None:
        return EvidenceGate(
            gate_id="calibration",
            name="概率校准",
            status=EvidenceGateStatus.MISSING,
            reasons=("缺少校准样本和Brier分数。",),
        )
    if profitability.calibration_sample_count <= 0 or profitability.brier_score is None:
        return EvidenceGate(
            gate_id="calibration",
            name="概率校准",
            status=EvidenceGateStatus.MISSING,
            reasons=("回测证据未包含概率校准样本。",),
        )
    if profitability.brier_score > request.max_brier_score:
        return EvidenceGate(
            gate_id="calibration",
            name="概率校准",
            status=EvidenceGateStatus.FAIL,
            reasons=(
                f"Brier分数超出门槛：{profitability.brier_score:.4f}/"
                f"{request.max_brier_score:.4f}。",
            ),
        )
    return EvidenceGate(
        gate_id="calibration",
        name="概率校准",
        status=EvidenceGateStatus.PASS,
        reasons=("概率校准证据通过。",),
    )


def _cost_stress_gate(cost_stress_passed: bool) -> EvidenceGate:
    if not cost_stress_passed:
        return EvidenceGate(
            gate_id="cost-stress",
            name="成本压力",
            status=EvidenceGateStatus.FAIL,
            reasons=("成本、滑点或换手压力测试未通过。",),
        )
    return EvidenceGate(
        gate_id="cost-stress",
        name="成本压力",
        status=EvidenceGateStatus.PASS,
        reasons=("成本压力输入通过。",),
    )


def _simulation_gate(
    request: DecisionRequest,
    simulation: SimulationEvidence | None,
) -> EvidenceGate:
    if simulation is None or simulation.execution_count == 0:
        status = (
            EvidenceGateStatus.MISSING
            if request.require_simulation_evidence
            else EvidenceGateStatus.WARN
        )
        return EvidenceGate(
            gate_id="paper-trading",
            name="模拟盘证据",
            status=status,
            reasons=("缺少模拟盘成交与偏差证据。",),
        )
    if simulation.threshold_breach_count > request.max_simulation_breaches:
        return EvidenceGate(
            gate_id="paper-trading",
            name="模拟盘证据",
            status=EvidenceGateStatus.FAIL,
            reasons=(
                f"模拟盘偏差超限次数：{simulation.threshold_breach_count}/"
                f"{request.max_simulation_breaches}。",
            ),
        )
    return EvidenceGate(
        gate_id="paper-trading",
        name="模拟盘证据",
        status=EvidenceGateStatus.PASS,
        reasons=("模拟盘成交偏差在容差内。",),
    )


def _real_order_gate() -> EvidenceGate:
    if REAL_ORDER_SUBMISSION_ENABLED:
        return EvidenceGate(
            gate_id="real-order-disabled",
            name="真实下单边界",
            status=EvidenceGateStatus.FAIL,
            reasons=("当前版本不得启用真实下单。",),
        )
    return EvidenceGate(
        gate_id="real-order-disabled",
        name="真实下单边界",
        status=EvidenceGateStatus.PASS,
        reasons=("当前版本没有真实下单路径。",),
    )


def _decision_signal(
    analysis_signal: FinalSignal,
    gates: tuple[EvidenceGate, ...],
) -> FinalSignal:
    if analysis_signal is FinalSignal.ABSTAIN:
        return FinalSignal.ABSTAIN
    blocking_gate_ids = {"data-health", "analysis-signal", "real-order-disabled"}
    if any(
        gate.status is EvidenceGateStatus.FAIL and gate.gate_id in blocking_gate_ids
        for gate in gates
    ):
        return FinalSignal.ABSTAIN
    if any(gate.status is not EvidenceGateStatus.PASS for gate in gates):
        return FinalSignal.WATCH
    return analysis_signal


def _execution_readiness(
    *,
    analysis_report: AnalysisReport,
    final_signal: FinalSignal,
    gates: tuple[EvidenceGate, ...],
    request: DecisionRequest,
) -> ExecutionReadiness:
    if analysis_report.data_health.block_signal or final_signal is FinalSignal.ABSTAIN:
        return ExecutionReadiness.NOT_ELIGIBLE
    gate_status_by_id = {gate.gate_id: gate.status for gate in gates}
    if any(status is EvidenceGateStatus.FAIL for status in gate_status_by_id.values()):
        return ExecutionReadiness.RESEARCH_ONLY
    if any(status is EvidenceGateStatus.MISSING for status in gate_status_by_id.values()):
        return (
            ExecutionReadiness.PAPER_READY
            if not request.require_simulation_evidence
            else ExecutionReadiness.RESEARCH_ONLY
        )
    if gate_status_by_id.get("paper-trading") is EvidenceGateStatus.WARN:
        return ExecutionReadiness.PAPER_READY
    if final_signal in TRADEABLE_DECISION_SIGNALS:
        return ExecutionReadiness.API_CANDIDATE
    return ExecutionReadiness.RESEARCH_ONLY


def _decision_confidence(
    analysis_report: AnalysisReport,
    gates: tuple[EvidenceGate, ...],
) -> float:
    probabilities = analysis_report.direction_probabilities
    dominant_probability = max(probabilities.up, probabilities.flat, probabilities.down)
    gate_multiplier = 1.0
    for gate in gates:
        if gate.status is EvidenceGateStatus.FAIL:
            gate_multiplier *= 0.35
        elif gate.status is EvidenceGateStatus.MISSING:
            gate_multiplier *= 0.55
        elif gate.status is EvidenceGateStatus.WARN:
            gate_multiplier *= 0.75
    return max(0.0, min(dominant_probability * gate_multiplier, 1.0))


def _positive_evidence(
    analysis_report: AnalysisReport,
    profitability: ProfitabilityEvidence | None,
    simulation: SimulationEvidence | None,
) -> tuple[str, ...]:
    values: list[str] = list(analysis_report.positive_drivers)
    if profitability is not None and profitability.total_return is not None:
        values.append(f"历史净收益：{profitability.total_return:.2%}")
    if profitability is not None and profitability.excess_return is not None:
        values.append(f"相对基准超额：{profitability.excess_return:.2%}")
    if simulation is not None:
        values.append(f"模拟盘净值：{simulation.net_asset_value:.2f}")
    return tuple(values) or ("暂无足够正向证据。",)


def _negative_evidence(
    gates: tuple[EvidenceGate, ...],
    analysis_report: AnalysisReport,
    profitability: ProfitabilityEvidence | None,
    simulation: SimulationEvidence | None,
) -> tuple[str, ...]:
    values: list[str] = list(analysis_report.negative_drivers)
    for gate in gates:
        if gate.status is not EvidenceGateStatus.PASS:
            values.extend(gate.reasons)
    if profitability is None:
        values.append("缺少可复现历史赚钱证据。")
    if simulation is None:
        values.append("缺少模拟盘成交偏差证据。")
    return tuple(dict.fromkeys(values)) or ("仍需持续监控模型、执行和市场风险。",)


def _caveats(final_signal: FinalSignal, readiness: ExecutionReadiness) -> tuple[str, ...]:
    values = [
        "所有收益和概率都来自历史样本或当前模型估计，不代表确定未来价格。",
        "当前版本不得提交真实订单；API_CANDIDATE也只表示未来接入评估状态。",
    ]
    if final_signal is FinalSignal.WATCH:
        values.append("证据门槛尚未完全通过，因此最终建议降级为观察。")
    if readiness is not ExecutionReadiness.API_CANDIDATE:
        values.append("未达到API执行候选门槛。")
    return tuple(values)


def _max_abs_slippage(state: SimulationAccountState) -> float | None:
    values = [
        abs(deviation.slippage_pct)
        for deviation in state.deviations
        if deviation.slippage_pct is not None and isfinite(deviation.slippage_pct)
    ]
    return max(values) if values else None
