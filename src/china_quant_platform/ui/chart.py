"""Lightweight Qt chart widget for the GUI alpha."""

from __future__ import annotations

from datetime import datetime

from PySide6 import QtCore, QtGui, QtWidgets

from china_quant_platform.ui.state import ChartOverlay, ChartPointState, ChartState
from china_quant_platform.ui.theme import (
    DEFAULT_THEME_MODE,
    ThemeColors,
    UiThemeMode,
    get_theme_colors,
)

_CHART_MARGIN_LEFT = 74
_CHART_MARGIN_RIGHT = 16
_CHART_MARGIN_TOP = 20
_CHART_MARGIN_BOTTOM = 34
_FORECAST_WIDTH = 58


class PriceChartWidget(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("priceChart")
        self.setMinimumHeight(260)
        self._chart_state = ChartState()
        self._theme_mode = DEFAULT_THEME_MODE

    @property
    def chart_state(self) -> ChartState:
        return self._chart_state

    @property
    def point_count(self) -> int:
        return self._chart_state.point_count

    def set_chart_state(self, chart_state: ChartState) -> None:
        self._chart_state = chart_state
        self.update()

    def set_theme_mode(self, theme_mode: UiThemeMode) -> None:
        self._theme_mode = theme_mode
        self.setProperty("themeMode", theme_mode.value)
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        colors = get_theme_colors(self._theme_mode)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(12, 12, -12, -12)
        painter.setPen(QtGui.QPen(QtGui.QColor(colors.separator_soft), 1))
        painter.setBrush(QtGui.QColor(colors.card))
        painter.drawRoundedRect(rect, 8, 8)

        points = self._chart_state.points
        if not points:
            painter.setPen(QtGui.QColor(colors.secondary_text))
            painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, "暂无图表数据")
            return

        plot_rect = rect.adjusted(
            _CHART_MARGIN_LEFT,
            _CHART_MARGIN_TOP,
            -_CHART_MARGIN_RIGHT,
            -_CHART_MARGIN_BOTTOM,
        )
        has_volume = ChartOverlay.VOLUME in self._chart_state.overlays
        has_forecast = ChartOverlay.FORECAST in self._chart_state.overlays and len(points) >= 2
        if has_volume:
            price_rect = QtCore.QRectF(
                plot_rect.left(),
                plot_rect.top(),
                plot_rect.width(),
                plot_rect.height() * 0.72,
            )
            volume_rect = QtCore.QRectF(
                plot_rect.left(),
                price_rect.bottom() + 10,
                plot_rect.width(),
                plot_rect.bottom() - price_rect.bottom() - 10,
            )
        else:
            price_rect = QtCore.QRectF(plot_rect)
            volume_rect = QtCore.QRectF()

        data_price_rect = (
            price_rect.adjusted(0, 0, -_FORECAST_WIDTH, 0) if has_forecast else price_rect
        )
        data_volume_rect = (
            volume_rect.adjusted(0, 0, -_FORECAST_WIDTH, 0)
            if has_forecast and has_volume
            else volume_rect
        )
        prices = [point.low_price for point in points] + [point.high_price for point in points]
        min_price = min(prices)
        max_price = max(prices)
        if min_price == max_price:
            min_price -= 1
            max_price += 1
        else:
            padding = (max_price - min_price) * 0.05
            min_price -= padding
            max_price += padding

        self._draw_axes_and_grid(
            painter,
            card_rect=QtCore.QRectF(rect),
            price_rect=price_rect,
            data_rect=data_price_rect,
            min_price=min_price,
            max_price=max_price,
        )

        self._draw_price_line(
            painter,
            data_price_rect,
            min_price=min_price,
            max_price=max_price,
        )

        if ChartOverlay.MOVING_AVERAGE in self._chart_state.overlays:
            self._draw_moving_average(
                painter,
                data_price_rect,
                min_price=min_price,
                max_price=max_price,
            )

        if has_forecast:
            self._draw_forecast(
                painter,
                price_rect,
                data_price_rect,
                min_price=min_price,
                max_price=max_price,
            )

        if ChartOverlay.SIGNALS in self._chart_state.overlays:
            self._draw_signal_markers(
                painter,
                data_price_rect,
                min_price=min_price,
                max_price=max_price,
            )

        if has_volume:
            self._draw_volume(painter, volume_rect, data_volume_rect)

    def _draw_axes_and_grid(
        self,
        painter: QtGui.QPainter,
        *,
        card_rect: QtCore.QRectF,
        price_rect: QtCore.QRectF,
        data_rect: QtCore.QRectF,
        min_price: float,
        max_price: float,
    ) -> None:
        colors = get_theme_colors(self._theme_mode)
        font = QtGui.QFont(self.font())
        font.setFamily("Consolas")
        font.setPointSize(8)
        painter.setFont(font)

        painter.setPen(QtGui.QPen(QtGui.QColor(colors.chart_grid), 1))
        for step in range(5):
            y = price_rect.top() + price_rect.height() * step / 4
            painter.drawLine(
                QtCore.QPointF(price_rect.left(), y),
                QtCore.QPointF(price_rect.right(), y),
            )
            value = max_price - (max_price - min_price) * step / 4
            painter.setPen(QtGui.QColor(colors.secondary_text))
            painter.drawText(
                QtCore.QRectF(card_rect.left() + 8, y - 9, _CHART_MARGIN_LEFT - 14, 18),
                QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
                f"{value:.3f}" if value < 10 else f"{value:.2f}",
            )
            painter.setPen(QtGui.QPen(QtGui.QColor(colors.chart_grid), 1))

        painter.setPen(QtGui.QColor(colors.secondary_text))
        painter.drawText(
            QtCore.QRectF(card_rect.left() + 8, price_rect.top() - 18, 88, 16),
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            "价格(CNY)",
        )
        painter.drawText(
            QtCore.QRectF(data_rect.right() - 44, card_rect.bottom() - 24, 58, 18),
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
            "时间",
        )
        self._draw_x_axis_labels(painter, card_rect, data_rect, colors)

    def _draw_x_axis_labels(
        self,
        painter: QtGui.QPainter,
        card_rect: QtCore.QRectF,
        data_rect: QtCore.QRectF,
        colors: ThemeColors,
    ) -> None:
        points = self._chart_state.points
        if not points:
            return
        indexes = (0, len(points) // 2, len(points) - 1)
        used_labels: set[int] = set()
        painter.setPen(QtGui.QColor(colors.secondary_text))
        for index in indexes:
            if index in used_labels:
                continue
            used_labels.add(index)
            x = _scaled_x(index, len(points), data_rect)
            label = _time_axis_label(points[index].time_label, self._chart_state.interval.value)
            if index == 0:
                label_rect = QtCore.QRectF(x, card_rect.bottom() - 24, 82, 18)
                alignment = QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
            elif index == len(points) - 1:
                label_rect = QtCore.QRectF(x - 82, card_rect.bottom() - 24, 82, 18)
                alignment = (
                    QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
                )
            else:
                label_rect = QtCore.QRectF(x - 41, card_rect.bottom() - 24, 82, 18)
                alignment = QtCore.Qt.AlignmentFlag.AlignCenter
            painter.drawText(label_rect, alignment, label)

    def _draw_price_line(
        self,
        painter: QtGui.QPainter,
        rect: QtCore.QRectF,
        *,
        min_price: float,
        max_price: float,
    ) -> None:
        colors = get_theme_colors(self._theme_mode)
        path = QtGui.QPainterPath()
        for index, point in enumerate(self._chart_state.points):
            x = _scaled_x(index, len(self._chart_state.points), rect)
            y = _scaled_y(point.close_price, min_price, max_price, rect)
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)

        painter.setPen(QtGui.QPen(QtGui.QColor(colors.blue), 2))
        painter.drawPath(path)

    def _draw_moving_average(
        self,
        painter: QtGui.QPainter,
        rect: QtCore.QRectF,
        *,
        min_price: float,
        max_price: float,
    ) -> None:
        points = self._chart_state.points
        if len(points) < 5:
            return

        path = QtGui.QPainterPath()
        has_first = False
        for index in range(4, len(points)):
            window = points[index - 4 : index + 1]
            average = sum(point.close_price for point in window) / 5
            x = _scaled_x(index, len(points), rect)
            y = _scaled_y(average, min_price, max_price, rect)
            if not has_first:
                path.moveTo(x, y)
                has_first = True
            else:
                path.lineTo(x, y)

        colors = get_theme_colors(self._theme_mode)
        painter.setPen(QtGui.QPen(QtGui.QColor(colors.orange), 1.6))
        painter.drawPath(path)

    def _draw_volume(
        self,
        painter: QtGui.QPainter,
        axis_rect: QtCore.QRectF,
        data_rect: QtCore.QRectF,
    ) -> None:
        points = self._chart_state.points
        max_volume = max((point.volume for point in points), default=0)
        if max_volume <= 0:
            return

        colors = get_theme_colors(self._theme_mode)
        painter.setPen(QtGui.QColor(colors.secondary_text))
        painter.drawText(
            QtCore.QRectF(axis_rect.left() - _CHART_MARGIN_LEFT + 8, axis_rect.top(), 50, 18),
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
            _compact_number(max_volume),
        )
        painter.drawText(
            QtCore.QRectF(
                axis_rect.left() - _CHART_MARGIN_LEFT + 8, axis_rect.bottom() - 18, 50, 18
            ),
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
            "成交量",
        )
        painter.setPen(QtGui.QPen(QtGui.QColor(colors.chart_grid), 1))
        painter.drawLine(axis_rect.bottomLeft(), axis_rect.bottomRight())

        bar_width = max(2, data_rect.width() / max(len(points), 1) * 0.68)
        label_step = max(1, round(18 / max(bar_width, 1)))
        original_font = QtGui.QFont(painter.font())
        label_font = QtGui.QFont(painter.font())
        label_font.setPointSize(7)
        painter.setFont(label_font)
        for index, point in enumerate(points):
            x = _scaled_x(index, len(points), data_rect) - bar_width / 2
            height = data_rect.height() * (point.volume / max_volume)
            y = data_rect.bottom() - height
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(_volume_color(point, colors))
            painter.drawRect(QtCore.QRectF(x, y, bar_width, height))
            if index % label_step == 0 or index == len(points) - 1:
                label_width = max(32.0, bar_width + 24)
                label_rect = QtCore.QRectF(
                    x - (label_width - bar_width) / 2,
                    max(data_rect.top(), y - 14),
                    label_width,
                    12,
                )
                painter.setPen(QtGui.QColor(colors.secondary_text))
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.drawText(
                    label_rect,
                    QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignBottom,
                    _compact_number(point.volume),
                )
        painter.setFont(original_font)

    def _draw_signal_markers(
        self,
        painter: QtGui.QPainter,
        rect: QtCore.QRectF,
        *,
        min_price: float,
        max_price: float,
    ) -> None:
        points = self._chart_state.points
        if len(points) < 3:
            return

        colors = get_theme_colors(self._theme_mode)
        markers = _turning_point_markers(points)[-8:]
        font = QtGui.QFont(self.font())
        font.setPointSize(7)
        font.setBold(True)
        painter.setFont(font)
        for index, label in markers:
            point = points[index]
            x = _scaled_x(index, len(points), rect)
            y = _scaled_y(point.close_price, min_price, max_price, rect)
            color = colors.green if label == "B" else colors.red
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(color))
            painter.drawEllipse(QtCore.QPointF(x, y), 6, 6)
            painter.setPen(QtGui.QColor(colors.highlighted_text))
            painter.drawText(
                QtCore.QRectF(x - 6, y - 6, 12, 12),
                QtCore.Qt.AlignmentFlag.AlignCenter,
                label,
            )

    def _draw_forecast(
        self,
        painter: QtGui.QPainter,
        price_rect: QtCore.QRectF,
        data_rect: QtCore.QRectF,
        *,
        min_price: float,
        max_price: float,
    ) -> None:
        points = self._chart_state.points
        if len(points) < 2:
            return

        colors = get_theme_colors(self._theme_mode)
        recent = points[-min(6, len(points)) :]
        slope = (recent[-1].close_price - recent[0].close_price) / max(len(recent) - 1, 1)
        volatility = _average_abs_move(recent) or (max_price - min_price) * 0.02
        last = points[-1]
        projected = last.close_price + slope * 3
        lower = projected - volatility * 2
        upper = projected + volatility * 2
        x0 = _scaled_x(len(points) - 1, len(points), data_rect)
        x1 = price_rect.right()
        y0 = _scaled_y(last.close_price, min_price, max_price, price_rect)
        y_mid = _scaled_y(projected, min_price, max_price, price_rect)
        y_low = _scaled_y(lower, min_price, max_price, price_rect)
        y_high = _scaled_y(upper, min_price, max_price, price_rect)

        band = QtGui.QPainterPath()
        band.moveTo(x0, y0)
        band.lineTo(x1, y_high)
        band.lineTo(x1, y_low)
        band.closeSubpath()
        band_color = QtGui.QColor(colors.blue)
        band_color.setAlpha(44)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(band_color)
        painter.drawPath(band)

        pen = QtGui.QPen(QtGui.QColor(colors.blue), 1.6)
        pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(QtCore.QPointF(x0, y0), QtCore.QPointF(x1, y_mid))
        painter.setPen(QtGui.QColor(colors.secondary_text))
        painter.drawText(
            QtCore.QRectF(x1 - 52, min(y_high, y_low) - 16, 52, 18),
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
            "Forecast",
        )


def _volume_color(point: ChartPointState, colors: ThemeColors) -> QtGui.QColor:
    if point.close_price > point.open_price:
        color = colors.red
    elif point.close_price < point.open_price:
        color = colors.green
    else:
        color = colors.chart_volume
    return QtGui.QColor(color)


def _turning_point_markers(points: tuple[ChartPointState, ...]) -> list[tuple[int, str]]:
    markers: list[tuple[int, str]] = []
    for index in range(1, len(points) - 1):
        previous_close = points[index - 1].close_price
        close_price = points[index].close_price
        next_close = points[index + 1].close_price
        if close_price <= previous_close and close_price < next_close:
            markers.append((index, "B"))
        elif close_price >= previous_close and close_price > next_close:
            markers.append((index, "S"))
    return markers


def _average_abs_move(points: tuple[ChartPointState, ...]) -> float:
    if len(points) < 2:
        return 0
    moves = [
        abs(points[index].close_price - points[index - 1].close_price)
        for index in range(1, len(points))
    ]
    return sum(moves) / len(moves)


def _scaled_x(index: int, count: int, rect: QtCore.QRectF) -> float:
    if count <= 1:
        return float(rect.center().x())
    return rect.left() + rect.width() * index / (count - 1)


def _scaled_y(value: float, minimum: float, maximum: float, rect: QtCore.QRectF) -> float:
    span = maximum - minimum
    normalized = (value - minimum) / span if span else 0.5
    normalized = max(0.0, min(1.0, normalized))
    return rect.bottom() - rect.height() * normalized


def _time_axis_label(value: str, interval: str) -> str:
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return value[:10]
    if interval in {"tick", "1m", "5m", "15m", "30m", "60m"}:
        return timestamp.strftime("%m-%d %H:%M")
    return timestamp.strftime("%Y-%m-%d")


def _compact_number(value: float) -> str:
    if value >= 100_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 10_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"


__all__ = ["PriceChartWidget"]
