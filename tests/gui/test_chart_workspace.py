"""GUI chart workspace tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from PySide6 import QtCore, QtWidgets

from china_quant_platform.domain import (
    AdjustmentMode,
    Bar,
    BarInterval,
    Quote,
    RecordQualityStatus,
)
from china_quant_platform.ui import (
    ApplicationViewModel,
    ChartOverlay,
    ChartPointState,
    ChartRangePreset,
    ChartSignalAction,
    ChartSignalMarkerState,
    ChartState,
    MainWindow,
    PriceChartWidget,
)


def aware_datetime(day: int = 29, hour: int = 15, minute: int = 0) -> datetime:
    return datetime(2026, 6, day, hour, minute, tzinfo=UTC)


def make_bar(day: int, close_price: float) -> Bar:
    start_time = aware_datetime(day, 9, 30)
    end_time = aware_datetime(day, 15, 0)
    return Bar(
        security_id="SSE:600519",
        interval=BarInterval.DAILY,
        start_time=start_time,
        end_time=end_time,
        trade_date=date(2026, 6, day),
        open_price=close_price - 1,
        high_price=close_price + 1,
        low_price=close_price - 2,
        close_price=close_price,
        volume=10_000 + day,
        amount=close_price * (10_000 + day),
        adjustment=AdjustmentMode.NONE,
        provider="fixture",
        schema_version="v1",
        source_time=end_time,
        observed_at=end_time,
        received_at=end_time + timedelta(seconds=1),
        quality_status=RecordQualityStatus.OK,
    )


def make_quote(minute: int, latest_price: float, security_id: str = "SSE:600519") -> Quote:
    source_time = aware_datetime(29, 15, minute)
    return Quote(
        security_id=security_id,
        latest_price=latest_price,
        previous_close=100,
        open_price=101,
        high_price=max(103, latest_price),
        low_price=99,
        volume=12_000 + minute,
        amount=latest_price * (12_000 + minute),
        provider="fixture",
        schema_version="v1",
        source_time=source_time,
        observed_at=source_time,
        received_at=source_time + timedelta(seconds=1),
        quality_status=RecordQualityStatus.OK,
    )


def test_chart_state_loads_bars_and_appends_realtime_quote() -> None:
    view_model = ApplicationViewModel(clock=lambda: aware_datetime())
    view_model.select_security("SSE:600519")
    generation = view_model.state.selection_generation

    view_model.load_chart_bars((make_bar(26, 101), make_bar(29, 103)), generation=generation)
    assert view_model.state.chart.point_count == 2

    view_model.apply_realtime_quote(make_quote(1, 104), generation=generation)
    assert view_model.state.chart.point_count == 3
    assert view_model.state.chart.realtime_update_count == 1
    assert view_model.state.chart.points[-1].reference_price == 100

    view_model.apply_realtime_quote(make_quote(2, 105), generation=generation - 1)
    assert view_model.state.chart.point_count == 3
    assert view_model.state.chart.realtime_update_count == 1


def test_chart_ignores_realtime_quote_for_other_security() -> None:
    view_model = ApplicationViewModel(clock=lambda: aware_datetime())
    view_model.select_security("SSE:600519")

    view_model.apply_realtime_quote(
        make_quote(1, 104, security_id="SSE:510300"),
        generation=view_model.state.selection_generation,
    )

    assert view_model.state.chart.point_count == 0


def test_chart_range_and_overlay_changes_preserve_security_and_adjustment() -> None:
    view_model = ApplicationViewModel(clock=lambda: aware_datetime())
    view_model.select_security("SSE:600519")
    view_model.set_chart_adjustment(AdjustmentMode.FORWARD)

    view_model.set_chart_range(ChartRangePreset.THREE_MONTHS)
    view_model.set_chart_overlay_enabled(ChartOverlay.MOVING_AVERAGE, True)

    assert view_model.state.selected_security_id == "SSE:600519"
    assert view_model.state.chart.adjustment is AdjustmentMode.FORWARD
    assert view_model.state.chart.range_preset is ChartRangePreset.THREE_MONTHS
    assert ChartOverlay.MOVING_AVERAGE in view_model.state.chart.overlays


def test_reselecting_current_security_keeps_existing_chart_points() -> None:
    view_model = ApplicationViewModel(clock=lambda: aware_datetime())
    view_model.select_security("SSE:600519")
    generation = view_model.state.selection_generation
    view_model.load_chart_bars(
        (make_bar(26, 101), make_bar(29, 103)),
        generation=generation,
    )

    view_model.select_security("SSE:600519")

    assert view_model.state.selected_security_id == "SSE:600519"
    assert view_model.state.chart.point_count == 2
    assert view_model.state.selection_generation == generation


def test_chart_workspace_renders_points_and_controls_state(qtbot: Any) -> None:
    view_model = ApplicationViewModel(clock=lambda: aware_datetime())
    window = MainWindow(view_model)
    qtbot.addWidget(window)

    view_model.select_security("SSE:600519")
    view_model.load_chart_bars(
        (make_bar(26, 101), make_bar(29, 103)),
        generation=view_model.state.selection_generation,
    )

    chart = window.findChild(PriceChartWidget, "priceChart")
    range_combo = window.findChild(QtWidgets.QComboBox, "chartRange")
    ma_overlay = window.findChild(QtWidgets.QCheckBox, "overlayMA")
    assert chart is not None
    assert range_combo is not None
    assert ma_overlay is not None
    assert chart.point_count == 2

    view_model.set_chart_adjustment(AdjustmentMode.BACKWARD)
    range_combo.setCurrentIndex(range_combo.findData(ChartRangePreset.THREE_MONTHS.value))
    ma_overlay.setChecked(True)

    assert view_model.state.selected_security_id == "SSE:600519"
    assert view_model.state.chart.adjustment is AdjustmentMode.BACKWARD
    assert view_model.state.chart.range_preset is ChartRangePreset.THREE_MONTHS
    assert ChartOverlay.MOVING_AVERAGE in view_model.state.chart.overlays
    assert "点数：2" in window.chart_summary_label.text()


def test_chart_hover_shows_price_and_change_pct(qtbot: Any) -> None:
    view_model = ApplicationViewModel(clock=lambda: aware_datetime())
    window = MainWindow(view_model)
    qtbot.addWidget(window)
    window.resize(1000, 680)
    window.show()
    qtbot.waitExposed(window)

    view_model.select_security("SSE:600519")
    view_model.load_chart_bars(
        (make_bar(26, 101), make_bar(29, 103)),
        generation=view_model.state.selection_generation,
    )
    view_model.apply_realtime_quote(
        make_quote(1, 104),
        generation=view_model.state.selection_generation,
    )
    chart = window.findChild(PriceChartWidget, "priceChart")
    assert chart is not None
    chart.repaint()
    chart.grab()
    hover_x = round(chart._last_data_x_rect.right()) - 1
    hover_y = round(chart._last_data_x_rect.center().y())

    qtbot.mouseMove(chart, QtCore.QPoint(hover_x, hover_y))

    assert chart.hover_index is not None
    assert "收盘/最新" in chart.toolTip()
    assert "涨跌:" in chart.toolTip()
    assert "%" in chart.toolTip()
    assert "+4.000" in chart.toolTip()
    assert "+4.00%" in chart.toolTip()


def test_chart_hover_includes_backtest_trade_signal(qtbot: Any) -> None:
    chart = PriceChartWidget()
    qtbot.addWidget(chart)
    chart.resize(720, 420)
    chart.show()

    points = tuple(
        ChartPointState.from_bar(bar)
        for bar in (make_bar(26, 101), make_bar(27, 102), make_bar(29, 103))
    )
    chart.set_chart_state(
        ChartState(
            points=points,
            overlays=frozenset({ChartOverlay.SIGNALS}),
            signals=(
                ChartSignalMarkerState(
                    trade_date=date(2026, 6, 29),
                    action=ChartSignalAction.BUY,
                    price=103,
                    label="B",
                    detail="买入 2026-06-29 @ 103.000",
                ),
            ),
        )
    )
    chart.repaint()

    qtbot.mouseMove(chart, QtCore.QPoint(chart.width() - 96, chart.height() // 2))

    assert chart.hover_index == 2
    assert "买入" in chart.toolTip()
    assert "103.000" in chart.toolTip()


def test_chart_signal_overlay_hides_incomplete_visible_trade_pairs(qtbot: Any) -> None:
    chart = PriceChartWidget()
    qtbot.addWidget(chart)
    chart.resize(720, 420)
    chart.show()
    points = tuple(
        ChartPointState.from_bar(bar)
        for bar in (make_bar(20, 10), make_bar(21, 12), make_bar(22, 11))
    )
    chart.set_chart_state(
        ChartState(
            points=points,
            overlays=frozenset({ChartOverlay.SIGNALS}),
            signals=(
                ChartSignalMarkerState(
                    trade_date=date(2026, 6, 19),
                    action=ChartSignalAction.BUY,
                    price=9,
                    label="B",
                    detail="窗口外买入",
                ),
                ChartSignalMarkerState(
                    trade_date=date(2026, 6, 20),
                    action=ChartSignalAction.SELL,
                    price=10,
                    label="S",
                    detail="孤立卖出",
                ),
                ChartSignalMarkerState(
                    trade_date=date(2026, 6, 21),
                    action=ChartSignalAction.BUY,
                    price=12,
                    label="B",
                    detail="窗口内买入",
                ),
                ChartSignalMarkerState(
                    trade_date=date(2026, 6, 22),
                    action=ChartSignalAction.SELL,
                    price=11,
                    label="S",
                    detail="窗口内卖出",
                ),
            ),
        )
    )
    chart.repaint()

    qtbot.mouseMove(chart, QtCore.QPoint(92, chart.height() // 2))

    assert "卖出: 10.000" not in chart.toolTip()

    qtbot.mouseMove(chart, QtCore.QPoint(chart.width() - 96, chart.height() // 2))

    assert "卖出: 11.000" in chart.toolTip()


def test_chart_backtest_button_draws_max_profit_trade_layer(qtbot: Any) -> None:
    view_model = ApplicationViewModel(clock=lambda: aware_datetime())
    window = MainWindow(view_model)
    qtbot.addWidget(window)

    button = window.findChild(QtWidgets.QPushButton, "chartBacktestButton")
    assert button is not None
    assert button.isEnabled() is False

    view_model.select_security("SSE:600519")
    view_model.set_strategy_max_trades_per_year(2)
    view_model.load_chart_bars(
        (
            make_bar(20, 10),
            make_bar(21, 12),
            make_bar(22, 8),
            make_bar(23, 14),
            make_bar(24, 7),
            make_bar(25, 16),
        ),
        generation=view_model.state.selection_generation,
    )
    normal_points = view_model.state.chart.points
    normal_overlays = view_model.state.chart.overlays
    normal_interval = view_model.state.chart.interval
    normal_range = view_model.state.chart.range_preset
    normal_summary = view_model.state.backtest.summary
    view_model._latest_decision_bars_by_security["SSE:600519"] = (
        make_bar(1, 100),
        make_bar(2, 101),
        make_bar(3, 102),
        make_bar(4, 103),
        make_bar(5, 104),
        make_bar(6, 105),
        make_bar(7, 106),
        make_bar(8, 107),
    )

    assert button.isEnabled() is True
    assert button.text() == "回测曲线"
    assert button.isChecked() is False

    qtbot.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)

    state = view_model.state
    assert state.chart_backtest_active is True
    assert state.backtest.status == "OPTIMIZED"
    assert state.backtest.trade_count == "2"
    assert "图表利润最大化" in state.backtest.summary
    assert "交易2/2次" in state.backtest.summary
    assert len(state.backtest.trades) == 2
    assert state.backtest.trades[0].startswith("1. 买入 2026-06-22 @ 8.000")
    assert state.backtest.trades[1].startswith("2. 买入 2026-06-24 @ 7.000")
    assert state.chart.points == normal_points
    assert state.chart.interval is normal_interval
    assert state.chart.range_preset is normal_range
    assert ChartOverlay.SIGNALS in state.chart.overlays
    assert tuple(signal.label for signal in state.chart.signals) == ("B", "S", "B", "S")
    assert (
        len([signal for signal in state.chart.signals if signal.action is ChartSignalAction.BUY])
        == 2
    )
    assert button.text() == "正常显示"
    assert button.isChecked() is True
    assert button.property("active") is True

    qtbot.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)

    state = view_model.state
    assert state.chart_backtest_active is False
    assert state.chart.points == normal_points
    assert state.chart.overlays == normal_overlays
    assert state.chart.signals == ()
    assert state.backtest.summary == normal_summary
    assert button.text() == "回测曲线"
    assert button.isChecked() is False
    assert button.property("active") is False


def test_signal_overlay_first_click_runs_current_chart_backtest(qtbot: Any) -> None:
    view_model = ApplicationViewModel(clock=lambda: aware_datetime())
    window = MainWindow(view_model)
    qtbot.addWidget(window)
    window.resize(1000, 680)
    window.show()
    qtbot.waitExposed(window)

    signal_toggle = window.findChild(QtWidgets.QCheckBox, "overlaySignals")
    assert signal_toggle is not None

    view_model.select_security("SSE:600519")
    view_model.set_strategy_max_trades_per_year(2)
    view_model.load_chart_bars(
        (
            make_bar(20, 10),
            make_bar(21, 12),
            make_bar(22, 8),
            make_bar(23, 14),
        ),
        generation=view_model.state.selection_generation,
    )
    normal_points = view_model.state.chart.points
    view_model._latest_decision_bars_by_security["SSE:600519"] = (
        make_bar(1, 100),
        make_bar(2, 101),
        make_bar(3, 102),
        make_bar(4, 103),
    )

    qtbot.mouseClick(signal_toggle, QtCore.Qt.MouseButton.LeftButton)

    state = view_model.state
    assert state.chart_backtest_active is True
    assert state.chart.points == normal_points
    assert tuple(signal.label for signal in state.chart.signals) == ("B", "S", "B", "S")
    assert state.backtest.status == "OPTIMIZED"
    assert signal_toggle.isChecked() is True

    qtbot.mouseClick(signal_toggle, QtCore.Qt.MouseButton.LeftButton)

    assert view_model.state.chart_backtest_active is False
    assert view_model.state.chart.signals == ()
    assert signal_toggle.isChecked() is False
