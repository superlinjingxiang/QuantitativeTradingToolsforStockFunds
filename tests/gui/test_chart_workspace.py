"""GUI chart workspace tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from PySide6 import QtWidgets

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
    ChartRangePreset,
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
