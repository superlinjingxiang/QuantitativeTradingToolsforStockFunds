"""PySide6 main window shell."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import cast

from PySide6 import QtCore, QtGui, QtWidgets

from china_quant_platform.domain import AdjustmentMode, BarInterval
from china_quant_platform.ui.chart import PriceChartWidget
from china_quant_platform.ui.state import AppUiState, ChartOverlay, ChartRangePreset, UiRunState
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
        self.search_input.installEventFilter(self)

        self.search_results = QtWidgets.QListWidget()
        self.search_results.setObjectName("securitySearchResults")
        self.search_results.setMaximumHeight(140)
        self.search_results.itemActivated.connect(self._activate_search_item)
        self.search_results.itemClicked.connect(self._activate_search_item)

        self.search_timer = QtCore.QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300)
        self.search_timer.timeout.connect(self._run_search)
        self.search_input.textChanged.connect(self._schedule_search)

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

        self.watchlist = QtWidgets.QListWidget()
        self.watchlist.setObjectName("watchlistItems")
        self.watchlist.itemActivated.connect(self._activate_security_item)
        self.watchlist.itemClicked.connect(self._activate_security_item)

        self.market_indices = QtWidgets.QListWidget()
        self.market_indices.setObjectName("marketIndexItems")
        self.market_indices.itemActivated.connect(self._activate_security_item)
        self.market_indices.itemClicked.connect(self._activate_security_item)

        self.market_overview_summary = QtWidgets.QLabel()
        self.market_overview_summary.setObjectName("marketOverviewSummary")
        self.market_overview_summary.setWordWrap(True)

        self.recent_securities = QtWidgets.QListWidget()
        self.recent_securities.setObjectName("recentSecurityItems")

        self.interval_combo = QtWidgets.QComboBox()
        self.interval_combo.setObjectName("chartInterval")
        for label, interval in (
            ("分时", BarInterval.TICK),
            ("1分", BarInterval.ONE_MINUTE),
            ("5分", BarInterval.FIVE_MINUTES),
            ("15分", BarInterval.FIFTEEN_MINUTES),
            ("30分", BarInterval.THIRTY_MINUTES),
            ("60分", BarInterval.SIXTY_MINUTES),
            ("日线", BarInterval.DAILY),
            ("周线", BarInterval.WEEKLY),
            ("月线", BarInterval.MONTHLY),
        ):
            self.interval_combo.addItem(label, interval.value)
        self.interval_combo.currentIndexChanged.connect(self._chart_interval_changed)

        self.range_combo = QtWidgets.QComboBox()
        self.range_combo.setObjectName("chartRange")
        for label, range_preset in (
            ("5日", ChartRangePreset.FIVE_DAYS),
            ("1月", ChartRangePreset.ONE_MONTH),
            ("3月", ChartRangePreset.THREE_MONTHS),
            ("6月", ChartRangePreset.SIX_MONTHS),
            ("1年", ChartRangePreset.ONE_YEAR),
            ("3年", ChartRangePreset.THREE_YEARS),
            ("5年", ChartRangePreset.FIVE_YEARS),
            ("自定义", ChartRangePreset.CUSTOM),
        ):
            self.range_combo.addItem(label, range_preset.value)
        self.range_combo.currentIndexChanged.connect(self._chart_range_changed)

        self.adjustment_combo = QtWidgets.QComboBox()
        self.adjustment_combo.setObjectName("chartAdjustment")
        for label, adjustment in (
            ("不复权", AdjustmentMode.NONE),
            ("前复权", AdjustmentMode.FORWARD),
            ("后复权", AdjustmentMode.BACKWARD),
        ):
            self.adjustment_combo.addItem(label, adjustment.value)
        self.adjustment_combo.currentIndexChanged.connect(self._chart_adjustment_changed)

        self.volume_overlay = self._overlay_checkbox("成交量", "overlayVolume", ChartOverlay.VOLUME)
        self.ma_overlay = self._overlay_checkbox("MA", "overlayMA", ChartOverlay.MOVING_AVERAGE)
        self.signal_overlay = self._overlay_checkbox("信号", "overlaySignals", ChartOverlay.SIGNALS)
        self.forecast_overlay = self._overlay_checkbox(
            "预测区间",
            "overlayForecast",
            ChartOverlay.FORECAST,
        )
        self.price_chart = PriceChartWidget()
        self.chart_summary_label = QtWidgets.QLabel()
        self.chart_summary_label.setObjectName("chartSummary")
        self.strategy_panel_label = self._panel_label("strategyPanelText")
        self.forecast_panel_label = self._panel_label("forecastPanelText")
        self.operation_panel_label = self._panel_label("operationPanelText")

        self.setCentralWidget(self._build_central_widget())
        self.statusBar().addPermanentWidget(self.status_label)
        self.view_model.state_changed.connect(self.render_state)
        self.render_state(self.view_model.state)

    @QtCore.Slot(object)
    def render_state(self, state: AppUiState) -> None:
        if self.search_input.text() != state.search_query:
            self.search_input.blockSignals(True)
            self.search_input.setText(state.search_query)
            self.search_input.blockSignals(False)

        self.search_results.blockSignals(True)
        self.search_results.clear()
        for candidate in state.search_results:
            candidate_text = (
                f"{candidate.symbol}  {candidate.name}  "
                f"{candidate.asset_type}  {candidate.exchange}"
            )
            item = QtWidgets.QListWidgetItem(candidate_text)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, candidate.security_id)
            self.search_results.addItem(item)
        if state.highlighted_search_index is not None:
            self.search_results.setCurrentRow(state.highlighted_search_index)
        self.search_results.setVisible(bool(state.search_results))
        self.search_results.blockSignals(False)

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
        self._sync_chart_controls(state)
        self.price_chart.set_chart_state(state.chart)
        self.chart_summary_label.setText(
            f"周期：{state.chart.interval.value}｜复权：{state.chart.adjustment.value}｜"
            f"范围：{state.chart.range_preset.value}｜点数：{state.chart.point_count}"
        )
        self._sync_market_and_watchlist(state)
        self.strategy_panel_label.setText(_strategy_panel_text(state))
        self.forecast_panel_label.setText(_forecast_panel_text(state))
        self.operation_panel_label.setText(_operation_panel_text(state))

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is self.search_input and event.type() == QtCore.QEvent.Type.KeyPress:
            key = cast(QtGui.QKeyEvent, event).key()
            if key == QtCore.Qt.Key.Key_Down:
                self.view_model.move_search_highlight(1)
                return True
            if key == QtCore.Qt.Key.Key_Up:
                self.view_model.move_search_highlight(-1)
                return True
            if key in {QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter}:
                self.view_model.confirm_highlighted_search()
                return True
        return super().eventFilter(watched, event)

    @QtCore.Slot()
    def _schedule_search(self) -> None:
        self.search_timer.start()

    @QtCore.Slot()
    def _run_search(self) -> None:
        self.view_model.search_securities(self.search_input.text())

    @QtCore.Slot(QtWidgets.QListWidgetItem)
    def _activate_search_item(self, item: QtWidgets.QListWidgetItem) -> None:
        security_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if isinstance(security_id, str):
            self.view_model.select_security(security_id)

    @QtCore.Slot(QtWidgets.QListWidgetItem)
    def _activate_security_item(self, item: QtWidgets.QListWidgetItem) -> None:
        security_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if isinstance(security_id, str):
            try:
                self.view_model.select_security(security_id)
            except KeyError:
                return

    @QtCore.Slot(int)
    def _chart_interval_changed(self, _index: int) -> None:
        value = self.interval_combo.currentData()
        if isinstance(value, str):
            self.view_model.set_chart_interval(BarInterval(value))

    @QtCore.Slot(int)
    def _chart_range_changed(self, _index: int) -> None:
        value = self.range_combo.currentData()
        if isinstance(value, str):
            self.view_model.set_chart_range(ChartRangePreset(value))

    @QtCore.Slot(int)
    def _chart_adjustment_changed(self, _index: int) -> None:
        value = self.adjustment_combo.currentData()
        if isinstance(value, str):
            self.view_model.set_chart_adjustment(AdjustmentMode(value))

    def _overlay_checkbox(
        self,
        text: str,
        object_name: str,
        overlay: ChartOverlay,
    ) -> QtWidgets.QCheckBox:
        checkbox = QtWidgets.QCheckBox(text)
        checkbox.setObjectName(object_name)
        checkbox.toggled.connect(
            lambda checked, selected_overlay=overlay: self.view_model.set_chart_overlay_enabled(
                selected_overlay,
                checked,
            )
        )
        return checkbox

    def _panel_label(self, object_name: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel()
        label.setObjectName(object_name)
        label.setWordWrap(True)
        label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
        return label

    def _sync_chart_controls(self, state: AppUiState) -> None:
        self._set_combo_data(self.interval_combo, state.chart.interval.value)
        self._set_combo_data(self.range_combo, state.chart.range_preset.value)
        self._set_combo_data(self.adjustment_combo, state.chart.adjustment.value)
        overlay_map = (
            (self.volume_overlay, ChartOverlay.VOLUME),
            (self.ma_overlay, ChartOverlay.MOVING_AVERAGE),
            (self.signal_overlay, ChartOverlay.SIGNALS),
            (self.forecast_overlay, ChartOverlay.FORECAST),
        )
        for checkbox, overlay in overlay_map:
            checkbox.blockSignals(True)
            checkbox.setChecked(overlay in state.chart.overlays)
            checkbox.blockSignals(False)

    def _set_combo_data(self, combo: QtWidgets.QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index < 0 or combo.currentIndex() == index:
            return
        combo.blockSignals(True)
        combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _sync_market_and_watchlist(self, state: AppUiState) -> None:
        overview = state.market_overview
        self.market_overview_summary.setText(
            "\n".join(
                [
                    f"市场状态：{overview.trend_state}",
                    f"市场广度：{overview.breadth_summary}",
                    f"成交额：{overview.turnover_summary}",
                    f"波动：{overview.volatility_state}",
                    f"数据：{overview.data_health_text}",
                ]
            )
        )
        self.market_overview_summary.setProperty("stale", overview.is_stale)
        self._set_list_items(
            self.market_indices,
            tuple(
                (
                    index.security_id,
                    f"{index.name}  {index.latest_value}  {index.change_pct}  {index.turnover}",
                )
                for index in overview.indices
            ),
        )
        self._set_list_items(
            self.watchlist,
            tuple(
                (
                    item.security_id,
                    f"[{item.group}] {item.symbol} {item.name}  "
                    f"{item.final_signal}  {item.latest_price}  "
                    f"{item.change_pct}  {item.data_health_text}",
                )
                for item in state.watchlist.items
            ),
        )

    def _set_list_items(
        self,
        widget: QtWidgets.QListWidget,
        entries: tuple[tuple[str, str], ...],
    ) -> None:
        widget.blockSignals(True)
        widget.clear()
        for security_id, text in entries:
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, security_id)
            widget.addItem(item)
        widget.blockSignals(False)

    def _build_central_widget(self) -> QtWidgets.QWidget:
        root = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        search_box = QtWidgets.QWidget()
        search_layout = QtWidgets.QVBoxLayout(search_box)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(4)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_results)

        top_bar = QtWidgets.QHBoxLayout()
        top_bar.addWidget(search_box, stretch=2)
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
        for title, widget in (
            ("自选列表", self.watchlist),
            ("指数", self.market_indices),
            ("最近访问", self.recent_securities),
        ):
            group = QtWidgets.QGroupBox(title)
            group_layout = QtWidgets.QVBoxLayout(group)
            if title == "指数":
                group_layout.addWidget(self.market_overview_summary)
            group_layout.addWidget(widget)
            layout.addWidget(group)
        return panel

    def _center_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.addWidget(self.interval_combo)
        toolbar.addWidget(self.range_combo)
        toolbar.addWidget(self.adjustment_combo)
        toolbar.addWidget(self.volume_overlay)
        toolbar.addWidget(self.ma_overlay)
        toolbar.addWidget(self.signal_overlay)
        toolbar.addWidget(self.forecast_overlay)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        layout.addWidget(self.price_chart, stretch=1)
        layout.addWidget(self.chart_summary_label)
        return panel

    def _right_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        for title, label in (
            ("当前策略", self.strategy_panel_label),
            ("预期走势", self.forecast_panel_label),
            ("操作与风险", self.operation_panel_label),
        ):
            group = QtWidgets.QGroupBox(title)
            group.setMinimumHeight(140)
            group_layout = QtWidgets.QVBoxLayout(group)
            group_layout.addWidget(label)
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


def _strategy_panel_text(state: AppUiState) -> str:
    strategy = state.analysis.strategy
    lines = [
        f"策略：{strategy.strategy_name}",
        f"ID/版本：{strategy.strategy_id} / {strategy.strategy_version}",
        f"周期：{strategy.horizon_label}",
        f"市场状态：{strategy.market_regime}",
        f"原始信号：{strategy.raw_signal}",
        f"模型/规则/快照：{strategy.model_version} / "
        f"{strategy.rule_version} / {strategy.data_snapshot_id}",
        _list_text("适用条件", strategy.applicable_conditions),
        _list_text("失效条件", strategy.invalidation_conditions),
    ]
    return "\n".join(lines)


def _forecast_panel_text(state: AppUiState) -> str:
    forecast = state.analysis.forecast
    return "\n".join(
        [
            f"方向：{forecast.direction_label}",
            f"概率：{forecast.probability_summary}",
            f"收益区间：{forecast.expected_return_range}",
            f"预期回撤：{forecast.expected_drawdown}",
            f"校准/说明：{forecast.confidence_note}",
            f"模型：{forecast.model_version}",
        ]
    )


def _operation_panel_text(state: AppUiState) -> str:
    operation = state.analysis.operation
    abstain_text = operation.abstain_reason or "--"
    lines = [
        f"最终操作：{operation.final_signal}",
        f"等级：{operation.grade}",
        f"有效期：{operation.valid_until}",
        f"仓位上限：{operation.target_position_limit}",
        f"不交易原因：{abstain_text}",
        _list_text("支持因素", operation.positive_drivers),
        _list_text("反对/风险", operation.negative_drivers),
        _list_text("退出/失效", operation.exit_or_invalidation_conditions),
    ]
    return "\n".join(lines)


def _list_text(title: str, values: tuple[str, ...]) -> str:
    if not values:
        return f"{title}：--"
    return f"{title}：" + "；".join(values)


__all__ = ["MainWindow", "create_application", "run_gui"]
