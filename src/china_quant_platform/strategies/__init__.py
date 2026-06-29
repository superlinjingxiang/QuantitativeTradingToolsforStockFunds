"""Strategy interfaces and versioned implementations."""

from china_quant_platform.strategies.base import (
    DriverDirection,
    Explanation,
    ExplanationDriver,
    RawSignal,
    RawSignalIntent,
    Strategy,
    StrategyCondition,
    StrategyContext,
    StrategyEvaluation,
    StrategyMetadata,
    WarmupSpec,
    evaluate_strategy,
)

__all__ = [
    "DriverDirection",
    "Explanation",
    "ExplanationDriver",
    "RawSignal",
    "RawSignalIntent",
    "Strategy",
    "StrategyCondition",
    "StrategyContext",
    "StrategyEvaluation",
    "StrategyMetadata",
    "WarmupSpec",
    "evaluate_strategy",
]
