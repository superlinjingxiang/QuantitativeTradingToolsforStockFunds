"""Lightweight Qt chart widget for the GUI alpha."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from china_quant_platform.ui.state import ChartOverlay, ChartState


class PriceChartWidget(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("priceChart")
        self.setMinimumHeight(260)
        self._chart_state = ChartState()

    @property
    def chart_state(self) -> ChartState:
        return self._chart_state

    @property
    def point_count(self) -> int:
        return self._chart_state.point_count

    def set_chart_state(self, chart_state: ChartState) -> None:
        self._chart_state = chart_state
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(12, 12, -12, -12)
        painter.fillRect(rect, QtGui.QColor("#ffffff"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#c7ccd4"), 1))
        painter.drawRect(rect)

        points = self._chart_state.points
        if not points:
            painter.setPen(QtGui.QColor("#4b5563"))
            painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, "暂无图表数据")
            return

        price_rect = QtCore.QRect(rect.left(), rect.top(), rect.width(), int(rect.height() * 0.72))
        volume_rect = QtCore.QRect(
            rect.left(),
            price_rect.bottom() + 8,
            rect.width(),
            rect.bottom() - price_rect.bottom() - 8,
        )
        prices = [point.close_price for point in points]
        min_price = min(prices)
        max_price = max(prices)
        if min_price == max_price:
            min_price -= 1
            max_price += 1

        path = QtGui.QPainterPath()
        for index, point in enumerate(points):
            x = _scaled_x(index, len(points), price_rect)
            y = _scaled_y(point.close_price, min_price, max_price, price_rect)
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)

        painter.setPen(QtGui.QPen(QtGui.QColor("#1f6feb"), 2))
        painter.drawPath(path)

        if ChartOverlay.VOLUME in self._chart_state.overlays:
            self._draw_volume(painter, volume_rect)

    def _draw_volume(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        points = self._chart_state.points
        max_volume = max((point.volume for point in points), default=0)
        if max_volume <= 0:
            return

        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor("#9ca3af"))
        bar_width = max(1, rect.width() / max(len(points), 1) * 0.7)
        for index, point in enumerate(points):
            x = _scaled_x(index, len(points), rect) - bar_width / 2
            height = rect.height() * (point.volume / max_volume)
            y = rect.bottom() - height
            painter.drawRect(QtCore.QRectF(x, y, bar_width, height))


def _scaled_x(index: int, count: int, rect: QtCore.QRect) -> float:
    if count <= 1:
        return float(rect.center().x())
    return rect.left() + rect.width() * index / (count - 1)


def _scaled_y(value: float, minimum: float, maximum: float, rect: QtCore.QRect) -> float:
    span = maximum - minimum
    normalized = (value - minimum) / span if span else 0.5
    return rect.bottom() - rect.height() * normalized


__all__ = ["PriceChartWidget"]
