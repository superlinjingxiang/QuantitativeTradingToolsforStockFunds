"""PySide6 main window shell."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import cast

from PySide6 import QtCore, QtWidgets

from china_quant_platform.ui.state import AppUiState, UiRunState
from china_quant_platform.ui.viewmodel import ApplicationViewModel


class MainWindow(QtWidgets.QMainWindow):
    def __init__(
        self,
        view_model: ApplicationViewModel | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.view_model = view_model or ApplicationViewModel(self)
        self.setWindowTitle("中国股票与基金量化分析平台")
        self.resize(1280, 820)

        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setObjectName("securitySearch")
        self.search_input.setPlaceholderText("代码 / 名称")

        self.health_banner = QtWidgets.QLabel()
        self.health_banner.setObjectName("healthBanner")
        self.health_banner.setMinimumHeight(32)
        self.health_banner.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        self.market_time_label = QtWidgets.QLabel("行情时间：--")
        self.market_time_label.setObjectName("marketTime")

        self.cancel_button = QtWidgets.QToolButton()
        self.cancel_button.setObjectName("cancelTaskButton")
        self.cancel_button.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogCancelButton)
        )
        self.cancel_button.setToolTip("取消后台任务")
        self.cancel_button.clicked.connect(self.view_model.cancel_active_task)

        self.settings_button = QtWidgets.QToolButton()
        self.settings_button.setObjectName("settingsButton")
        self.settings_button.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileDialogDetailedView)
        )
        self.settings_button.setToolTip("设置")

        self.status_label = QtWidgets.QLabel()
        self.status_label.setObjectName("stateLabel")

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("workspaceTabs")
        for title in ("市场", "策略", "回测", "模拟账户", "风险", "知识中心"):
            self.tabs.addTab(self._placeholder_page(title), title)

        self.setCentralWidget(self._build_central_widget())
        self.statusBar().addPermanentWidget(self.status_label)
        self.view_model.state_changed.connect(self.render_state)
        self.render_state(self.view_model.state)

    @QtCore.Slot(object)
    def render_state(self, state: AppUiState) -> None:
        self.health_banner.setText(state.banner_text)
        self.health_banner.setProperty("blocked", state.is_signal_blocked)
        self.health_banner.setProperty("state", state.run_state.value)
        self.health_banner.style().unpolish(self.health_banner)
        self.health_banner.style().polish(self.health_banner)

        selected = state.selected_security_id or "--"
        self.status_label.setText(
            f"状态：{state.run_state.value}｜任务：{state.task_status.value}｜标的：{selected}"
        )
        self.cancel_button.setEnabled(state.run_state is UiRunState.BACKTEST_RUNNING)

    def _build_central_widget(self) -> QtWidgets.QWidget:
        root = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        top_bar = QtWidgets.QHBoxLayout()
        top_bar.addWidget(self.search_input, stretch=2)
        top_bar.addWidget(self.health_banner, stretch=3)
        top_bar.addWidget(self.market_time_label, stretch=1)
        top_bar.addWidget(self.cancel_button)
        top_bar.addWidget(self.settings_button)
        layout.addLayout(top_bar)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setObjectName("mainSplitter")
        splitter.addWidget(self._left_panel())
        splitter.addWidget(self._center_panel())
        splitter.addWidget(self._right_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 2)
        layout.addWidget(splitter, stretch=1)
        layout.addWidget(self.tabs)

        root.setStyleSheet(
            """
            QLabel#healthBanner {
                border: 1px solid #8a8f98;
                border-radius: 4px;
                padding: 4px 10px;
                background: #eef6f0;
                color: #14351f;
            }
            QLabel#healthBanner[blocked="true"] {
                background: #fde8e8;
                color: #5b1111;
                border-color: #c24141;
            }
            """
        )
        return root

    def _left_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        for title in ("自选列表", "指数", "最近访问"):
            group = QtWidgets.QGroupBox(title)
            group_layout = QtWidgets.QVBoxLayout(group)
            group_layout.addWidget(QtWidgets.QListWidget())
            layout.addWidget(group)
        return panel

    def _center_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        chart_area = QtWidgets.QFrame()
        chart_area.setObjectName("chartWorkspace")
        chart_area.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        chart_layout = QtWidgets.QVBoxLayout(chart_area)
        chart_title = QtWidgets.QLabel("价格 / K线 / 成交量")
        chart_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        chart_layout.addWidget(chart_title)
        layout.addWidget(chart_area, stretch=1)
        return panel

    def _right_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        for title in ("当前策略", "预期走势", "操作与风险"):
            group = QtWidgets.QGroupBox(title)
            group.setMinimumHeight(140)
            layout.addWidget(group)
        return panel

    def _placeholder_page(self, title: str) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        label = QtWidgets.QLabel(title)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        return page


def create_application(argv: Sequence[str] | None = None) -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is not None:
        return cast(QtWidgets.QApplication, app)
    return QtWidgets.QApplication(list(argv or sys.argv))


def run_gui(argv: Sequence[str] | None = None) -> int:
    app = create_application(argv)
    window = MainWindow()
    window.show()
    return app.exec()


__all__ = ["MainWindow", "create_application", "run_gui"]
