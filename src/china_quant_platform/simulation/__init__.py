"""Paper trading and simulated brokerage package."""

from china_quant_platform.simulation.broker import (
    REAL_ORDER_SUBMISSION_ENABLED,
    SignalExecutionDeviation,
    SimulationAccountMetrics,
    SimulationAccountState,
    SimulationBroker,
    SimulationBrokerConfig,
    SimulationExecutionRecord,
    SimulationOrderRecord,
    SimulationOrderResult,
    SimulationOrderStatus,
    export_simulation_state,
    restore_simulation_state,
    simulation_state_checksum,
)

__all__ = [
    "REAL_ORDER_SUBMISSION_ENABLED",
    "SignalExecutionDeviation",
    "SimulationAccountMetrics",
    "SimulationAccountState",
    "SimulationBroker",
    "SimulationBrokerConfig",
    "SimulationExecutionRecord",
    "SimulationOrderRecord",
    "SimulationOrderResult",
    "SimulationOrderStatus",
    "export_simulation_state",
    "restore_simulation_state",
    "simulation_state_checksum",
]
