"""Qt ViewModel and cancellable task shell."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6 import QtCore

from china_quant_platform.domain import DataHealth, DomainError
from china_quant_platform.ui.state import (
    AppUiState,
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
        result_factory: Callable[[], object] | None = None,
        error_factory: Callable[[], BaseException] | None = None,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.name = name
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

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._state = AppUiState()
        self._active_task: CancellableQtTask | None = None

    @property
    def state(self) -> AppUiState:
        return self._state

    def select_security(self, security_id: str) -> None:
        self._set_state(
            self._state.model_copy(
                update={
                    "selection_generation": self._state.selection_generation + 1,
                    "selected_security_id": security_id,
                    "run_state": UiRunState.LOADING_CACHE_HISTORY,
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
            result_factory=lambda: name,
            error_factory=fail_with,
            parent=self,
        )
        task.finished.connect(lambda _result: self._complete_task(name))
        task.cancelled.connect(lambda: self._mark_task_cancelled(name))
        task.failed.connect(self._fail_task)
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

    def _complete_task(self, name: str) -> None:
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

    def _mark_task_cancelled(self, name: str) -> None:
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

    def _fail_task(self, error: Any) -> None:
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


__all__ = ["ApplicationViewModel", "CancellableQtTask"]
