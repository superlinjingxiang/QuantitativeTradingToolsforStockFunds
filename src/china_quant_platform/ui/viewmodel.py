"""Qt ViewModel and cancellable task shell."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from PySide6 import QtCore

from china_quant_platform.data import SecurityMasterService
from china_quant_platform.domain import DataHealth, DomainError
from china_quant_platform.domain.enums import AssetType, Currency, Exchange, SecurityStatus
from china_quant_platform.domain.models import SecurityRef
from china_quant_platform.ui.state import (
    AppUiState,
    SearchCandidateState,
    UiErrorState,
    UiRunState,
    UiTaskStatus,
    run_state_for_error,
    run_state_for_health,
)


class CancellableQtTask(QtCore.QObject):
    """Small non-blocking task handle used by the GUI shell and tests."""

    finished = QtCore.Signal(object)
    failed = QtCore.Signal(object)
    cancelled = QtCore.Signal()

    def __init__(
        self,
        *,
        name: str,
        delay_ms: int,
        generation: int = 0,
        result_factory: Callable[[], object] | None = None,
        error_factory: Callable[[], BaseException] | None = None,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.name = name
        self.generation = generation
        self._result_factory = result_factory or (lambda: None)
        self._error_factory = error_factory
        self._cancelled = False
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._finish)

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def start(self) -> None:
        self._timer.start()

    @QtCore.Slot()
    def cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        self._timer.stop()
        self.cancelled.emit()

    @QtCore.Slot()
    def _finish(self) -> None:
        if self._cancelled:
            self.cancelled.emit()
            return
        if self._error_factory is not None:
            self.failed.emit(self._error_factory())
            return
        self.finished.emit(self._result_factory())


class ApplicationViewModel(QtCore.QObject):
    state_changed = QtCore.Signal(object)

    def __init__(
        self,
        parent: QtCore.QObject | None = None,
        *,
        security_master: SecurityMasterService | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(parent)
        self._state = AppUiState()
        self._active_task: CancellableQtTask | None = None
        self._security_master = security_master or build_demo_security_master()
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    @property
    def state(self) -> AppUiState:
        return self._state

    @property
    def active_task(self) -> CancellableQtTask | None:
        return self._active_task

    def search_securities(self, query: str, *, as_of: date | None = None) -> None:
        stripped_query = query.strip()
        if not stripped_query:
            self._set_state(
                self._state.model_copy(
                    update={
                        "search_query": "",
                        "search_results": (),
                        "highlighted_search_index": None,
                        "run_state": UiRunState.IDLE,
                    }
                )
            )
            return

        results = self._security_master.search(
            stripped_query,
            as_of=as_of,
            limit=10,
            include_inactive=True,
        )
        candidates = tuple(SearchCandidateState.from_search_result(result) for result in results)
        self._set_state(
            self._state.model_copy(
                update={
                    "search_query": stripped_query,
                    "search_results": candidates,
                    "highlighted_search_index": 0 if candidates else None,
                    "run_state": UiRunState.SEARCHING,
                    "latest_error": None,
                }
            )
        )

    def move_search_highlight(self, delta: int) -> None:
        if not self._state.search_results:
            return
        current = self._state.highlighted_search_index
        next_index = 0 if current is None else (current + delta) % len(self._state.search_results)
        self._set_state(self._state.model_copy(update={"highlighted_search_index": next_index}))

    def confirm_highlighted_search(self) -> None:
        index = self._state.highlighted_search_index
        if index is None or index >= len(self._state.search_results):
            return
        self.select_security(self._state.search_results[index].security_id)

    def select_security(self, security_id: str) -> None:
        if self._active_task is not None:
            self.cancel_active_task()

        selected_at = self._clock()
        security = self._security_master.select_security(
            security_id,
            selected_at=selected_at,
            as_of=selected_at.date(),
        )
        next_generation = self._state.selection_generation + 1
        self._set_state(
            self._state.model_copy(
                update={
                    "selection_generation": next_generation,
                    "selected_security_id": security.security_id,
                    "search_query": "",
                    "search_results": (),
                    "highlighted_search_index": None,
                    "run_state": UiRunState.LOADING_CACHE_HISTORY,
                    "task_status": UiTaskStatus.IDLE,
                    "active_task_name": None,
                    "latest_error": None,
                }
            )
        )

    def apply_data_health(self, data_health: DataHealth) -> None:
        self._set_state(
            self._state.model_copy(
                update={
                    "data_health": data_health,
                    "run_state": run_state_for_health(data_health),
                    "latest_error": None,
                }
            )
        )

    def apply_domain_error(self, error: DomainError) -> None:
        self._set_state(
            self._state.model_copy(
                update={
                    "run_state": run_state_for_error(error.kind),
                    "latest_error": UiErrorState(
                        kind=error.kind,
                        user_message=error.user_message,
                        engineering_message=error.engineering_message,
                        retryable=error.retryable,
                        blocks_signal=error.blocks_signal,
                    ),
                }
            )
        )

    def start_demo_task(
        self,
        *,
        name: str = "demo",
        delay_ms: int = 100,
        fail_with: Callable[[], DomainError] | None = None,
    ) -> CancellableQtTask:
        if self._active_task is not None:
            self.cancel_active_task()

        task = CancellableQtTask(
            name=name,
            delay_ms=delay_ms,
            generation=self._state.selection_generation,
            result_factory=lambda: name,
            error_factory=fail_with,
            parent=self,
        )
        generation = task.generation
        task.finished.connect(lambda _result: self._complete_task(name, generation))
        task.cancelled.connect(lambda: self._mark_task_cancelled(name, generation))
        task.failed.connect(lambda error: self._fail_task(error, generation))
        self._active_task = task
        self._set_state(
            self._state.model_copy(
                update={
                    "run_state": UiRunState.BACKTEST_RUNNING,
                    "task_status": UiTaskStatus.RUNNING,
                    "active_task_name": name,
                    "latest_error": None,
                }
            )
        )
        task.start()
        return task

    def cancel_active_task(self) -> None:
        if self._active_task is None:
            return
        self._set_state(
            self._state.model_copy(
                update={
                    "run_state": UiRunState.BACKTEST_CANCELLING,
                    "task_status": UiTaskStatus.CANCELLING,
                }
            )
        )
        self._active_task.cancel()

    def _complete_task(self, name: str, generation: int) -> None:
        if generation != self._state.selection_generation:
            return
        self._active_task = None
        self._set_state(
            self._state.model_copy(
                update={
                    "run_state": UiRunState.BACKTEST_COMPLETED,
                    "task_status": UiTaskStatus.COMPLETED,
                    "active_task_name": name,
                }
            )
        )

    def _mark_task_cancelled(self, name: str, generation: int) -> None:
        if generation != self._state.selection_generation:
            return
        self._active_task = None
        self._set_state(
            self._state.model_copy(
                update={
                    "run_state": UiRunState.IDLE,
                    "task_status": UiTaskStatus.CANCELLED,
                    "active_task_name": name,
                }
            )
        )

    def _fail_task(self, error: Any, generation: int) -> None:
        if generation != self._state.selection_generation:
            return
        self._active_task = None
        if isinstance(error, DomainError):
            self.apply_domain_error(error)
            self._set_state(
                self._state.model_copy(
                    update={
                        "task_status": UiTaskStatus.FAILED,
                        "active_task_name": None,
                    }
                )
            )
            return
        self._set_state(
            self._state.model_copy(
                update={
                    "run_state": UiRunState.BACKTEST_FAILED,
                    "task_status": UiTaskStatus.FAILED,
                    "active_task_name": None,
                }
            )
        )

    def _set_state(self, state: AppUiState) -> None:
        self._state = state
        self.state_changed.emit(state)


def build_demo_security_master() -> SecurityMasterService:
    securities = (
        SecurityRef(
            security_id="SSE:600519",
            symbol="600519",
            name="贵州茅台",
            asset_type=AssetType.STOCK,
            exchange=Exchange.SSE,
            currency=Currency.CNY,
            listed_date=date(2001, 8, 27),
            status_date=date(2026, 6, 28),
            status=SecurityStatus.ACTIVE,
            aliases=("Kweichow Moutai", "茅台"),
        ),
        SecurityRef(
            security_id="SSE:510300",
            symbol="510300",
            name="沪深300ETF",
            asset_type=AssetType.ETF,
            exchange=Exchange.SSE,
            currency=Currency.CNY,
            listed_date=date(2012, 5, 28),
            status_date=date(2026, 6, 28),
            status=SecurityStatus.ACTIVE,
            aliases=("CSI300 ETF", "300ETF"),
        ),
        SecurityRef(
            security_id="FUND:000001",
            symbol="000001",
            name="华夏成长混合",
            asset_type=AssetType.MUTUAL_FUND,
            exchange=Exchange.FUND_COMPANY,
            currency=Currency.CNY,
            listed_date=date(2001, 12, 18),
            status_date=date(2026, 6, 28),
            status=SecurityStatus.ACTIVE,
            aliases=("Huaxia Growth",),
        ),
    )
    return SecurityMasterService.from_securities(securities)


__all__ = ["ApplicationViewModel", "CancellableQtTask", "build_demo_security_master"]
