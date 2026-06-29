"""GUI state models for the PySide6 shell."""

from __future__ import annotations

from enum import StrEnum

from china_quant_platform.data import SecuritySearchResult
from china_quant_platform.domain import DataHealth, DataHealthStatus, DomainErrorKind
from china_quant_platform.domain.base import DomainModel


class UiRunState(StrEnum):
    IDLE = "IDLE"
    SEARCHING = "SEARCHING"
    LOADING_CACHE_HISTORY = "LOADING_CACHE_HISTORY"
    FETCHING_REMOTE_HISTORY = "FETCHING_REMOTE_HISTORY"
    CONNECTING_REALTIME = "CONNECTING_REALTIME"
    REALTIME_RUNNING = "REALTIME_RUNNING"
    COMPUTING_STRATEGY = "COMPUTING_STRATEGY"
    DATA_STALE = "DATA_STALE"
    DATA_QUALITY_BLOCKED = "DATA_QUALITY_BLOCKED"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    MODEL_OUT_OF_DISTRIBUTION = "MODEL_OUT_OF_DISTRIBUTION"
    BACKTEST_RUNNING = "BACKTEST_RUNNING"
    BACKTEST_CANCELLING = "BACKTEST_CANCELLING"
    BACKTEST_FAILED = "BACKTEST_FAILED"
    BACKTEST_COMPLETED = "BACKTEST_COMPLETED"
    ERROR = "ERROR"


class UiTaskStatus(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class UiErrorState(DomainModel):
    kind: DomainErrorKind
    user_message: str
    engineering_message: str
    retryable: bool
    blocks_signal: bool


class SearchCandidateState(DomainModel):
    security_id: str
    symbol: str
    name: str
    asset_type: str
    exchange: str
    status: str
    score: float
    matched_fields: tuple[str, ...]

    @classmethod
    def from_search_result(cls, result: SecuritySearchResult) -> SearchCandidateState:
        security = result.security
        return cls(
            security_id=security.security_id,
            symbol=security.symbol,
            name=security.name,
            asset_type=security.asset_type.value,
            exchange=security.exchange.value,
            status=security.status.value,
            score=result.score,
            matched_fields=result.matched_fields,
        )


class AppUiState(DomainModel):
    selection_generation: int = 0
    selected_security_id: str | None = None
    search_query: str = ""
    search_results: tuple[SearchCandidateState, ...] = ()
    highlighted_search_index: int | None = None
    run_state: UiRunState = UiRunState.IDLE
    task_status: UiTaskStatus = UiTaskStatus.IDLE
    active_task_name: str | None = None
    data_health: DataHealth | None = None
    latest_error: UiErrorState | None = None

    @property
    def is_signal_blocked(self) -> bool:
        return self.data_health.block_signal if self.data_health is not None else False

    @property
    def banner_text(self) -> str:
        if self.data_health is None:
            return "数据健康：未连接"
        issue_text = "；".join(self.data_health.issues)
        if issue_text:
            return f"数据健康：{self.data_health.status.value}｜{issue_text}"
        return f"数据健康：{self.data_health.status.value}"


def run_state_for_health(data_health: DataHealth) -> UiRunState:
    if not data_health.block_signal:
        return UiRunState.REALTIME_RUNNING
    if data_health.status is DataHealthStatus.STALE:
        return UiRunState.DATA_STALE
    return UiRunState.DATA_QUALITY_BLOCKED


def run_state_for_error(kind: DomainErrorKind) -> UiRunState:
    match kind:
        case DomainErrorKind.DATA_STALE:
            return UiRunState.DATA_STALE
        case DomainErrorKind.DATA_INVALID | DomainErrorKind.UNAUTHORIZED_DATA:
            return UiRunState.DATA_QUALITY_BLOCKED
        case DomainErrorKind.INSUFFICIENT_HISTORY:
            return UiRunState.INSUFFICIENT_HISTORY
        case DomainErrorKind.MODEL_OUT_OF_DISTRIBUTION:
            return UiRunState.MODEL_OUT_OF_DISTRIBUTION
        case _:
            return UiRunState.ERROR


__all__ = [
    "AppUiState",
    "SearchCandidateState",
    "UiErrorState",
    "UiRunState",
    "UiTaskStatus",
    "run_state_for_error",
    "run_state_for_health",
]
