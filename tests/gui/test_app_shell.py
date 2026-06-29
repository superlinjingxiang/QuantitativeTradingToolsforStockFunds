"""PySide6 app shell and ViewModel tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from PySide6 import QtCore, QtWidgets

from china_quant_platform.domain import DataHealth, DataHealthStatus, DataStale
from china_quant_platform.ui import ApplicationViewModel, MainWindow, UiRunState, UiTaskStatus


def aware_datetime() -> datetime:
    return datetime(2026, 6, 29, 15, 0, tzinfo=UTC)


def stale_health() -> DataHealth:
    return DataHealth(
        status=DataHealthStatus.STALE,
        block_signal=True,
        as_of=aware_datetime(),
        issues=("stale quote",),
    )


def invalid_health() -> DataHealth:
    return DataHealth(
        status=DataHealthStatus.INVALID,
        block_signal=True,
        as_of=aware_datetime(),
        issues=("invalid ohlc",),
    )


def test_view_model_maps_data_health_to_blocking_state() -> None:
    view_model = ApplicationViewModel()

    view_model.apply_data_health(stale_health())

    assert view_model.state.run_state is UiRunState.DATA_STALE
    assert view_model.state.is_signal_blocked is True
    assert "stale quote" in view_model.state.banner_text


def test_view_model_searches_local_security_master_and_selects_candidate() -> None:
    view_model = ApplicationViewModel(clock=aware_datetime)

    view_model.search_securities("茅台")
    assert view_model.state.run_state is UiRunState.SEARCHING
    assert view_model.state.search_results[0].security_id == "SSE:600519"

    view_model.confirm_highlighted_search()

    assert view_model.state.selection_generation == 1
    assert view_model.state.selected_security_id == "SSE:600519"
    assert view_model.state.search_results == ()
    assert view_model.state.run_state is UiRunState.LOADING_CACHE_HISTORY


def test_security_selection_cancels_old_task_and_ignores_old_generation() -> None:
    view_model = ApplicationViewModel(clock=aware_datetime)
    old_task = view_model.start_demo_task(name="old-subscription", delay_ms=1000)

    view_model.select_security("SSE:600519")
    old_task.finished.emit("late-old-result")

    assert old_task.is_cancelled is True
    assert view_model.state.selection_generation == 1
    assert view_model.state.selected_security_id == "SSE:600519"
    assert view_model.state.run_state is UiRunState.LOADING_CACHE_HISTORY
    assert view_model.state.task_status is UiTaskStatus.IDLE


def test_main_window_updates_health_banner(qtbot: Any) -> None:
    view_model = ApplicationViewModel()
    window = MainWindow(view_model)
    qtbot.addWidget(window)

    view_model.apply_data_health(invalid_health())

    banner = window.findChild(QtWidgets.QLabel, "healthBanner")
    assert banner is not None
    assert "INVALID" in banner.text()
    assert banner.property("blocked") is True


def test_search_box_debounces_results_and_enter_confirms_selection(qtbot: Any) -> None:
    view_model = ApplicationViewModel(clock=aware_datetime)
    window = MainWindow(view_model)
    qtbot.addWidget(window)

    search_input = window.findChild(QtWidgets.QLineEdit, "securitySearch")
    search_results = window.findChild(QtWidgets.QListWidget, "securitySearchResults")
    assert search_input is not None
    assert search_results is not None

    qtbot.keyClicks(search_input, "600519")
    qtbot.waitUntil(lambda: search_results.count() == 1, timeout=1000)
    qtbot.keyClick(search_input, QtCore.Qt.Key.Key_Return)

    assert view_model.state.selected_security_id == "SSE:600519"
    assert view_model.state.selection_generation == 1
    assert search_results.count() == 0


def test_search_box_arrow_keys_move_highlight(qtbot: Any) -> None:
    view_model = ApplicationViewModel(clock=aware_datetime)
    window = MainWindow(view_model)
    qtbot.addWidget(window)

    search_input = window.findChild(QtWidgets.QLineEdit, "securitySearch")
    search_results = window.findChild(QtWidgets.QListWidget, "securitySearchResults")
    assert search_input is not None
    assert search_results is not None

    qtbot.keyClicks(search_input, "00")
    qtbot.waitUntil(lambda: search_results.count() >= 2, timeout=1000)
    assert search_results.currentRow() == 0

    qtbot.keyClick(search_input, QtCore.Qt.Key.Key_Down)

    assert view_model.state.highlighted_search_index == 1
    assert search_results.currentRow() == 1


def test_demo_task_can_be_cancelled_without_blocking_qt(qtbot: Any) -> None:
    view_model = ApplicationViewModel()
    view_model.start_demo_task(name="backtest-demo", delay_ms=1000)
    flag: list[bool] = []
    QtCore.QTimer.singleShot(0, lambda: flag.append(True))

    qtbot.waitUntil(lambda: bool(flag), timeout=500)
    view_model.cancel_active_task()
    qtbot.waitUntil(
        lambda: view_model.state.task_status is UiTaskStatus.CANCELLED,
        timeout=500,
    )

    assert view_model.state.run_state is UiRunState.IDLE
    assert view_model.state.active_task_name == "backtest-demo"


def test_typed_domain_error_is_visible_in_state_and_window(qtbot: Any) -> None:
    view_model = ApplicationViewModel()
    window = MainWindow(view_model)
    qtbot.addWidget(window)

    view_model.start_demo_task(
        name="stale-error-demo",
        delay_ms=0,
        fail_with=lambda: DataStale("fixture quote is stale"),
    )
    qtbot.waitUntil(lambda: view_model.state.latest_error is not None, timeout=500)

    assert view_model.state.run_state is UiRunState.DATA_STALE
    assert view_model.state.task_status is UiTaskStatus.FAILED
    assert view_model.state.latest_error is not None
    assert view_model.state.latest_error.blocks_signal is True
    assert "Data is stale" in view_model.state.latest_error.user_message
    assert "DATA_STALE" in window.status_label.text()
