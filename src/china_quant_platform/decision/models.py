"""Decision hub contracts that combine signals, evidence, and execution gates."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from china_quant_platform.domain import AnalysisReport, FinalSignal
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import NonEmptyString, SecurityId

TRADEABLE_DECISION_SIGNALS = frozenset(
    {
        FinalSignal.BUY_CANDIDATE,
        FinalSignal.ADD_CANDIDATE,
        FinalSignal.HOLD,
        FinalSignal.REDUCE,
        FinalSignal.SELL,
    }
)

NO_PROFIT_GUARANTEE_STATEMENT = (
    "本报告只提供概率化研究建议和可复核证据，不保证盈利，也不构成真实交易指令。"
)


class EvidenceGateStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    MISSING = "MISSING"


class ExecutionReadiness(StrEnum):
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    PAPER_READY = "PAPER_READY"
    API_CANDIDATE = "API_CANDIDATE"


class DecisionRequest(DomainModel):
    security_id: SecurityId
    as_of: AwareDatetime
    evidence_window: NonEmptyString = "latest"
    min_backtest_trades: int = Field(default=10, ge=1)
    max_backtest_drawdown: float = Field(default=0.25, ge=0, le=1)
    max_brier_score: float = Field(default=0.25, ge=0, le=1)
    min_sharpe_ratio: float = Field(default=0.75, ge=0)
    min_drawdown_improvement: float = Field(default=0.20, ge=0, le=1)
    max_simulation_breaches: int = Field(default=0, ge=0)
    require_simulation_evidence: bool = True


class EvidenceGate(DomainModel):
    gate_id: NonEmptyString
    name: NonEmptyString
    status: EvidenceGateStatus
    reasons: tuple[NonEmptyString, ...] = ()

    @model_validator(mode="after")
    def failed_or_missing_gates_require_reasons(self) -> Self:
        if (
            self.status in {EvidenceGateStatus.FAIL, EvidenceGateStatus.MISSING}
            and not self.reasons
        ):
            raise ValueError("failed or missing gates require reasons")
        return self


class ProfitabilityEvidence(DomainModel):
    source: NonEmptyString
    strategy_id: NonEmptyString
    strategy_version: NonEmptyString
    total_return: float | None = None
    annualized_return: float | None = None
    annualized_volatility: float | None = Field(default=None, ge=0)
    sharpe_ratio: float | None = None
    calmar_ratio: float | None = None
    max_drawdown: float | None = None
    benchmark_total_return: float | None = None
    benchmark_max_drawdown: float | None = None
    excess_return: float | None = None
    trade_count: int = Field(default=0, ge=0)
    turnover: float | None = Field(default=None, ge=0)
    cost_drag: float | None = Field(default=None, ge=0)
    average_position_fraction: float | None = Field(default=None, gt=0, le=1)
    stress_round_trip_cost_bps: float | None = Field(default=None, ge=0)
    stress_total_return: float | None = None
    stress_max_drawdown: float | None = None
    cost_stress_passed: bool | None = None
    calibration_sample_count: int = Field(default=0, ge=0)
    brier_score: float | None = Field(default=None, ge=0)
    walk_forward_positive_ratio: float | None = Field(default=None, ge=0, le=1)
    walk_forward_participation_ratio: float | None = Field(default=None, ge=0, le=1)
    walk_forward_excess_ratio: float | None = Field(default=None, ge=0, le=1)
    walk_forward_median_return: float | None = None
    checksum: NonEmptyString | None = None
    notes: tuple[NonEmptyString, ...] = ()

    @property
    def has_profitability(self) -> bool:
        return self.total_return is not None and self.total_return > 0

    @property
    def has_benchmark_comparison(self) -> bool:
        return self.benchmark_total_return is not None and self.excess_return is not None


class SimulationEvidence(DomainModel):
    account_id: NonEmptyString
    net_asset_value: float = Field(ge=0)
    realized_pnl: float
    unrealized_pnl: float
    order_count: int = Field(ge=0)
    execution_count: int = Field(ge=0)
    deviation_count: int = Field(ge=0)
    threshold_breach_count: int = Field(ge=0)
    max_abs_slippage_pct: float | None = Field(default=None, ge=0)
    checksum: NonEmptyString | None = None
    notes: tuple[NonEmptyString, ...] = ()


class DecisionReport(DomainModel):
    request: DecisionRequest
    analysis_report: AnalysisReport
    final_signal: FinalSignal
    execution_readiness: ExecutionReadiness
    confidence: float = Field(ge=0, le=1)
    target_position_limit: float | None = Field(default=None, ge=0, le=1)
    valid_until: AwareDatetime
    profitability: ProfitabilityEvidence | None = None
    simulation: SimulationEvidence | None = None
    gates: tuple[EvidenceGate, ...]
    positive_evidence: tuple[NonEmptyString, ...]
    negative_evidence: tuple[NonEmptyString, ...]
    caveats: tuple[NonEmptyString, ...]
    no_profit_guarantee: Literal[
        "本报告只提供概率化研究建议和可复核证据，不保证盈利，也不构成真实交易指令。"
    ] = "本报告只提供概率化研究建议和可复核证据，不保证盈利，也不构成真实交易指令。"
    real_order_submission_enabled: Literal[False] = False

    @model_validator(mode="after")
    def enforce_decision_invariants(self) -> Self:
        if self.request.security_id != self.analysis_report.security_id:
            raise ValueError(
                "decision request and analysis report must reference the same security"
            )
        if self.final_signal in TRADEABLE_DECISION_SIGNALS:
            non_pass = tuple(
                gate for gate in self.gates if gate.status is not EvidenceGateStatus.PASS
            )
            if non_pass:
                raise ValueError("tradeable decision reports require every evidence gate to pass")
        if self.execution_readiness is ExecutionReadiness.API_CANDIDATE:
            if self.final_signal not in TRADEABLE_DECISION_SIGNALS:
                raise ValueError("API candidates require a tradeable final signal")
            if any(gate.status is not EvidenceGateStatus.PASS for gate in self.gates):
                raise ValueError("API candidates require all evidence gates to pass")
        if not self.positive_evidence or not self.negative_evidence:
            raise ValueError("decision reports require both positive and negative evidence")
        if not self.caveats:
            raise ValueError("decision reports require caveats")
        return self
