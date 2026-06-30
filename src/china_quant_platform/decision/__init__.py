"""Strategy decision hub package."""

from china_quant_platform.decision.hub import (
    DecisionHub,
    profitability_from_backtest,
    simulation_evidence_from_state,
)
from china_quant_platform.decision.models import (
    NO_PROFIT_GUARANTEE_STATEMENT,
    DecisionReport,
    DecisionRequest,
    EvidenceGate,
    EvidenceGateStatus,
    ExecutionReadiness,
    ProfitabilityEvidence,
    SimulationEvidence,
)
from china_quant_platform.decision.research import (
    build_bar_profitability_evidence,
    build_research_analysis_report,
    build_research_decision_from_market_data,
)

__all__ = [
    "DecisionHub",
    "DecisionReport",
    "DecisionRequest",
    "EvidenceGate",
    "EvidenceGateStatus",
    "ExecutionReadiness",
    "NO_PROFIT_GUARANTEE_STATEMENT",
    "ProfitabilityEvidence",
    "SimulationEvidence",
    "build_bar_profitability_evidence",
    "build_research_analysis_report",
    "build_research_decision_from_market_data",
    "profitability_from_backtest",
    "simulation_evidence_from_state",
]
