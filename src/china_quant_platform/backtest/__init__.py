"""Event-driven backtest engine package."""

from china_quant_platform.backtest.core import (
    BacktestCancellationToken,
    BacktestClock,
    BacktestEngine,
    BacktestEvent,
    BacktestEventLoop,
    BacktestEventType,
    BacktestRunResult,
    DeterministicExecutionSimulator,
    ExecutionReport,
    ExecutionStatus,
    OrderIntent,
    TradingSession,
)

__all__ = [
    "BacktestCancellationToken",
    "BacktestClock",
    "BacktestEngine",
    "BacktestEvent",
    "BacktestEventLoop",
    "BacktestEventType",
    "BacktestRunResult",
    "DeterministicExecutionSimulator",
    "ExecutionReport",
    "ExecutionStatus",
    "OrderIntent",
    "TradingSession",
]
