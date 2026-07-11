"""PySide6 main window shell."""

from __future__ import annotations

import html
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PySide6 import QtCore, QtGui, QtWidgets

from china_quant_platform.data import create_default_market_data_provider
from china_quant_platform.domain import AdjustmentMode, BarInterval
from china_quant_platform.ui.chart import PriceChartWidget
from china_quant_platform.ui.state import (
    AppUiState,
    ChartOverlay,
    ChartRangePreset,
    MarketIndexPanelState,
    MarketOverviewPanelState,
    StrategyMode,
    UiTaskStatus,
)
from china_quant_platform.ui.theme import (
    DEFAULT_THEME_MODE,
    UiThemeMode,
    apply_theme_palette,
    coerce_theme_mode,
    style_sheet_for,
)
from china_quant_platform.ui.viewmodel import ApplicationViewModel

THEME_SETTINGS_KEY = "appearance/theme"


class MainWindow(QtWidgets.QMainWindow):
    def __init__(
        self,
        view_model: ApplicationViewModel | None = None,
        parent: QtWidgets.QWidget | None = None,
        *,
        settings: QtCore.QSettings | None = None,
        initial_theme: UiThemeMode | str | None = None,
    ) -> None:
        super().__init__(parent)
        self.view_model = view_model or ApplicationViewModel(self)
        self.settings = settings or QtCore.QSettings("ChinaQuantPlatform", "DesktopShell")
        self._theme_mode = (
            coerce_theme_mode(initial_theme)
            if initial_theme is not None
            else _load_theme_mode(self.settings)
        )
        self._theme_actions: dict[UiThemeMode, QtGui.QAction] = {}
        self._last_health_popup_key: tuple[str, tuple[str, ...]] | None = None
        self._health_popups: list[QtWidgets.QMessageBox] = []
        self._strategy_info_dialogs: list[QtWidgets.QDialog] = []
        self.setWindowTitle("中国股票与基金量化分析平台")
        self.resize(1440, 900)
        self.setObjectName("mainWindow")

        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setObjectName("securitySearch")
        self.search_input.setPlaceholderText("代码 / 名称")
        self.search_input.installEventFilter(self)
        self.search_input.returnPressed.connect(self._submit_search)

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
        self.settings_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)

        self.strategy_horizon_combo = QtWidgets.QComboBox()
        self.strategy_horizon_combo.setObjectName("strategyHorizon")
        self.strategy_horizon_combo.setToolTip(
            "选择短线或长线预测策略，系统会自动匹配预测窗口和回测参数"
        )
        for label, mode in (
            ("短线策略", StrategyMode.SHORT_TERM),
            ("长线策略", StrategyMode.LONG_TERM),
        ):
            self.strategy_horizon_combo.addItem(label, mode.value)
        self.strategy_horizon_combo.currentIndexChanged.connect(self._strategy_horizon_changed)

        self.strategy_trade_spin = QtWidgets.QSpinBox()
        self.strategy_trade_spin.setObjectName("strategyMaxTradesPerYear")
        self.strategy_trade_spin.setRange(1, 60)
        self.strategy_trade_spin.setSuffix(" 次")
        self.strategy_trade_spin.setToolTip("当前策略/图表回测最多交易次数")
        self.strategy_trade_spin.valueChanged.connect(self._strategy_trade_count_changed)

        self.chart_backtest_button = QtWidgets.QPushButton("回测曲线")
        self.chart_backtest_button.setObjectName("chartBacktestButton")
        self.chart_backtest_button.setCheckable(True)
        self.chart_backtest_button.setToolTip("按当前策略期限和交易上限寻找历史最大利润路径")
        self.chart_backtest_button.clicked.connect(self.view_model.run_chart_profit_backtest)

        self.theme_combo = QtWidgets.QComboBox()
        self.theme_combo.setObjectName("themeModeCombo")
        self.theme_combo.addItem("黑色主题", UiThemeMode.DARK.value)
        self.theme_combo.addItem("白色主题", UiThemeMode.LIGHT.value)
        self.theme_combo.currentIndexChanged.connect(self._theme_combo_changed)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setObjectName("stateLabel")

        self.knowledge_search = QtWidgets.QLineEdit()
        self.knowledge_search.setObjectName("knowledgeSearch")
        self.knowledge_search.setPlaceholderText("术语")
        self.knowledge_search.textChanged.connect(self.view_model.search_knowledge)

        self.knowledge_topics = QtWidgets.QListWidget()
        self.knowledge_topics.setObjectName("knowledgeTopics")
        self.knowledge_topics.itemActivated.connect(self._activate_knowledge_topic)
        self.knowledge_topics.itemClicked.connect(self._activate_knowledge_topic)

        self.knowledge_detail = QtWidgets.QTextBrowser()
        self.knowledge_detail.setObjectName("knowledgeDetail")
        self.knowledge_detail.setOpenExternalLinks(False)

        self.backtest_summary_label = self._panel_label("backtestSummaryText")
        self.backtest_metrics_label = self._panel_label("backtestMetricsText")
        self.backtest_notes_label = self._panel_label("backtestNotesText")
        self.strategy_info_button = QtWidgets.QPushButton("策略说明")
        self.strategy_info_button.setObjectName("strategyInfoButton")
        self.strategy_info_button.setToolTip("查看当前回测策略说明和代码位置")
        self.strategy_info_button.clicked.connect(self._show_strategy_info_dialog)
        self.run_backtest_button = QtWidgets.QPushButton("重新回测")
        self.run_backtest_button.setObjectName("runBacktestButton")
        self.run_backtest_button.clicked.connect(self.view_model.run_current_backtest)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("workspaceTabs")
        for title in ("市场", "策略", "回测", "模拟账户", "风险", "知识中心"):
            if title == "知识中心":
                page = self._knowledge_page()
            elif title == "回测":
                page = self._backtest_page()
            else:
                page = self._placeholder_page(title)
            self.tabs.addTab(page, title)

        self.watchlist = QtWidgets.QListWidget()
        self.watchlist.setObjectName("watchlistItems")
        self.watchlist.itemActivated.connect(self._activate_security_item)
        self.watchlist.itemClicked.connect(self._activate_security_item)

        self.add_watchlist_button = QtWidgets.QToolButton()
        self.add_watchlist_button.setObjectName("addWatchlistItem")
        self.add_watchlist_button.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogApplyButton)
        )
        self.add_watchlist_button.setToolTip("添加当前标的到自选列表")
        self.add_watchlist_button.clicked.connect(self._add_selected_to_watchlist)

        self.remove_watchlist_button = QtWidgets.QToolButton()
        self.remove_watchlist_button.setObjectName("removeWatchlistItem")
        self.remove_watchlist_button.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_TrashIcon)
        )
        self.remove_watchlist_button.setToolTip("从自选列表删除当前标的")
        self.remove_watchlist_button.clicked.connect(self._remove_current_watchlist_item)

        self.market_indices = QtWidgets.QListWidget()
        self.market_indices.setObjectName("marketIndexItems")
        self.market_indices.itemActivated.connect(self._activate_security_item)
        self.market_indices.itemClicked.connect(self._activate_security_item)

        self.refresh_market_button = QtWidgets.QToolButton()
        self.refresh_market_button.setObjectName("refreshMarketOverview")
        self.refresh_market_button.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.refresh_market_button.setToolTip("刷新主要指数")
        self.refresh_market_button.clicked.connect(self.view_model.refresh_market_overview)

        self.market_overview_summary = QtWidgets.QLabel()
        self.market_overview_summary.setObjectName("marketOverviewSummary")
        self.market_overview_summary.setWordWrap(True)
        self.market_overview_summary.setTextFormat(QtCore.Qt.TextFormat.RichText)

        self.recent_securities = QtWidgets.QListWidget()
        self.recent_securities.setObjectName("recentSecurityItems")
        self.recent_securities.itemActivated.connect(self._activate_security_item)
        self.recent_securities.itemClicked.connect(self._activate_security_item)

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
        self.signal_overlay = self._overlay_checkbox(
            "回测信号",
            "overlaySignals",
            ChartOverlay.SIGNALS,
        )
        self.signal_overlay.setToolTip(
            "显示当前策略回测产生的完整买卖点；回测曲线模式下显示当前图表最大利润买卖点"
        )
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
        self.decision_panel_label = self._panel_label("decisionPanelText")

        self.setCentralWidget(self._build_central_widget())
        self.statusBar().addPermanentWidget(self.status_label)
        self._configure_settings_menu()
        self.set_theme_mode(self._theme_mode, persist=False)
        self.view_model.state_changed.connect(self.render_state)
        self.render_state(self.view_model.state)

    @property
    def theme_mode(self) -> UiThemeMode:
        return self._theme_mode

    def set_theme_mode(self, theme_mode: UiThemeMode | str, *, persist: bool = True) -> None:
        selected_mode = coerce_theme_mode(theme_mode)
        self._theme_mode = selected_mode
        self.setProperty("themeMode", selected_mode.value)
        application = QtWidgets.QApplication.instance()
        if application is not None:
            apply_theme_palette(cast(QtWidgets.QApplication, application), selected_mode)
        self.setStyleSheet(style_sheet_for(selected_mode))
        self.price_chart.set_theme_mode(selected_mode)
        for mode, action in self._theme_actions.items():
            action.setChecked(mode is selected_mode)
        self._set_combo_data(self.theme_combo, selected_mode.value)
        self.settings_button.setToolTip(f"设置：{_theme_label(selected_mode)}")
        if persist:
            self.settings.setValue(THEME_SETTINGS_KEY, selected_mode.value)
            self.settings.sync()

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

        self.health_banner.setText(_health_banner_text(state))
        self.health_banner.setProperty("blocked", state.is_signal_blocked)
        self.health_banner.setProperty("state", state.run_state.value)
        self.health_banner.style().unpolish(self.health_banner)
        self.health_banner.style().polish(self.health_banner)
        self._maybe_show_data_health_popup(state)
        latest_point_time = state.chart.points[-1].time_label if state.chart.points else "--"
        self.market_time_label.setText(f"行情时间：{latest_point_time}")

        selected = state.selected_security_id or "--"
        self.status_label.setText(
            f"状态：{state.run_state.value}｜任务：{state.task_status.value}｜标的：{selected}"
        )
        self.cancel_button.setEnabled(
            state.task_status
            in {
                UiTaskStatus.RUNNING,
                UiTaskStatus.CANCELLING,
            }
        )
        self._sync_chart_controls(state)
        self._sync_strategy_controls(state)
        self.price_chart.set_chart_state(state.chart)
        self.chart_summary_label.setText(
            f"周期：{state.chart.interval.value}｜复权：{state.chart.adjustment.value}｜"
            f"范围：{state.chart.range_preset.value}｜点数：{state.chart.point_count}"
        )
        self._sync_market_and_watchlist(state)
        self._sync_watchlist_buttons(state)
        self._sync_knowledge(state)
        self.strategy_panel_label.setText(_strategy_panel_text(state))
        self.forecast_panel_label.setText(_forecast_panel_text(state))
        self.operation_panel_label.setText(_operation_panel_text(state))
        self.decision_panel_label.setText(_decision_panel_text(state))
        self._sync_backtest_panel(state)

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
                self._submit_search()
                return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.view_model.shutdown()
        super().closeEvent(event)

    def _configure_settings_menu(self) -> None:
        menu = QtWidgets.QMenu(self)
        theme_group = QtGui.QActionGroup(self)
        theme_group.setExclusive(True)
        for mode in (UiThemeMode.DARK, UiThemeMode.LIGHT):
            action = QtGui.QAction(_theme_label(mode), self)
            action.setCheckable(True)
            action.setData(mode.value)
            action.triggered.connect(
                lambda _checked=False, selected_mode=mode: self.set_theme_mode(selected_mode)
            )
            theme_group.addAction(action)
            menu.addAction(action)
            self._theme_actions[mode] = action
        self.settings_button.setMenu(menu)

    @QtCore.Slot()
    def _schedule_search(self) -> None:
        self.search_timer.start()

    @QtCore.Slot()
    def _run_search(self) -> None:
        self.view_model.search_securities(self.search_input.text())

    @QtCore.Slot()
    def _submit_search(self) -> None:
        self.search_timer.stop()
        query = self.search_input.text().strip()
        if not query:
            return
        self.view_model.search_securities(query)
        self.view_model.confirm_highlighted_search()

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

    def _maybe_show_data_health_popup(self, state: AppUiState) -> None:
        data_health = state.data_health
        if data_health is None or not data_health.issues:
            self._last_health_popup_key = None
            return
        if not _has_online_failure_issue(data_health.issues):
            return
        key = (data_health.status.value, data_health.issues)
        if key == self._last_health_popup_key:
            return
        self._last_health_popup_key = key
        status = data_health.status.value
        issues = data_health.issues
        QtCore.QTimer.singleShot(
            0,
            lambda status=status, issues=issues: self._show_data_health_popup(status, issues),
        )

    def _show_data_health_popup(self, status: str, issues: tuple[str, ...]) -> None:
        popup = QtWidgets.QMessageBox(self)
        popup.setObjectName("dataHealthPopup")
        popup.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        popup.setWindowTitle("联网行情提示")
        popup.setText(f"数据健康：{status}")
        popup.setInformativeText("\n".join(issues))
        popup.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        popup.setModal(False)
        popup.finished.connect(lambda _result, box=popup: self._forget_health_popup(box))
        self._health_popups.append(popup)
        popup.show()

    def _forget_health_popup(self, popup: QtWidgets.QMessageBox) -> None:
        if popup in self._health_popups:
            self._health_popups.remove(popup)

    @QtCore.Slot()
    def _add_selected_to_watchlist(self) -> None:
        security_id = self.view_model.state.selected_security_id
        if security_id is not None:
            self.view_model.add_watchlist_item(security_id, pinned=True)

    @QtCore.Slot()
    def _remove_current_watchlist_item(self) -> None:
        item = self.watchlist.currentItem()
        security_id = item.data(QtCore.Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(security_id, str):
            selected = self.view_model.state.selected_security_id
            watchlist_ids = {item.security_id for item in self.view_model.state.watchlist.items}
            security_id = selected if selected in watchlist_ids else None
        if isinstance(security_id, str):
            self.view_model.remove_watchlist_item(security_id)

    @QtCore.Slot(QtWidgets.QListWidgetItem)
    def _activate_knowledge_topic(self, item: QtWidgets.QListWidgetItem) -> None:
        topic_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if isinstance(topic_id, str):
            self.view_model.select_knowledge_topic(topic_id)

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

    @QtCore.Slot(int)
    def _strategy_horizon_changed(self, _index: int) -> None:
        value = self.strategy_horizon_combo.currentData()
        if isinstance(value, str):
            self.view_model.set_strategy_mode(StrategyMode(value))

    @QtCore.Slot(int)
    def _strategy_trade_count_changed(self, value: int) -> None:
        self.view_model.set_strategy_max_trades_per_year(value)

    @QtCore.Slot(int)
    def _theme_combo_changed(self, _index: int) -> None:
        value = self.theme_combo.currentData()
        if isinstance(value, str):
            self.set_theme_mode(value)

    @QtCore.Slot()
    def _show_strategy_info_dialog(self) -> None:
        info = _strategy_info_for_state(self.view_model.state)
        dialog = QtWidgets.QDialog(self)
        dialog.setObjectName("strategyInfoDialog")
        dialog.setWindowTitle("当前回测策略说明")
        dialog.resize(620, 480)

        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setSpacing(10)

        title = QtWidgets.QLabel(info.title)
        title.setObjectName("strategyInfoTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        body = QtWidgets.QTextBrowser()
        body.setObjectName("strategyInfoText")
        body.setOpenExternalLinks(False)
        body.setPlainText(
            "\n\n".join(
                (
                    info.subtitle,
                    info.body,
                    f"代码位置：{info.code_path}",
                )
            )
        )
        layout.addWidget(body, stretch=1)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        code_button = QtWidgets.QPushButton("打开代码")
        code_button.setObjectName("strategyInfoCodeButton")
        code_button.setProperty("sourcePath", str(info.code_path))
        code_button.setEnabled(info.code_path.exists())
        code_button.setToolTip(str(info.code_path))
        code_button.clicked.connect(lambda _checked=False: _open_code_file(info.code_path))
        buttons.addWidget(code_button)
        close_button = QtWidgets.QPushButton("关闭")
        close_button.clicked.connect(dialog.close)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        dialog.finished.connect(lambda _result=0, item=dialog: self._forget_strategy_dialog(item))
        self._strategy_info_dialogs.append(dialog)
        dialog.show()

    def _forget_strategy_dialog(self, dialog: QtWidgets.QDialog) -> None:
        if dialog in self._strategy_info_dialogs:
            self._strategy_info_dialogs.remove(dialog)

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
        label.setTextFormat(QtCore.Qt.TextFormat.RichText)
        label.setMinimumHeight(0)
        label.setContentsMargins(0, 0, 4, 0)
        label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Minimum,
        )
        label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
        return label

    def _panel_scroll_area(
        self,
        label: QtWidgets.QLabel,
        object_name: str,
    ) -> QtWidgets.QScrollArea:
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setObjectName(object_name)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setWidget(label)
        return scroll_area

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

    def _sync_strategy_controls(self, state: AppUiState) -> None:
        controls = state.strategy_controls
        self._set_combo_data(self.strategy_horizon_combo, controls.mode.value)
        self.strategy_trade_spin.blockSignals(True)
        self.strategy_trade_spin.setValue(controls.max_trades_per_year)
        self.strategy_trade_spin.blockSignals(False)

    def _sync_backtest_panel(self, state: AppUiState) -> None:
        backtest = state.backtest
        self.backtest_summary_label.setText(backtest.summary)
        self.backtest_metrics_label.setText(_backtest_metrics_text(state))
        self.backtest_notes_label.setText(_backtest_notes_text(state))
        self.run_backtest_button.setEnabled(state.selected_security_id is not None)
        self.chart_backtest_button.setText(
            "正常显示" if state.chart_backtest_active else "回测曲线"
        )
        self.chart_backtest_button.setToolTip(
            "关闭回测买卖层，恢复当前正常图表"
            if state.chart_backtest_active
            else "按当前策略期限和交易上限寻找历史最大利润路径"
        )
        self.chart_backtest_button.blockSignals(True)
        self.chart_backtest_button.setChecked(state.chart_backtest_active)
        self.chart_backtest_button.blockSignals(False)
        self.chart_backtest_button.setProperty("active", state.chart_backtest_active)
        self.chart_backtest_button.style().unpolish(self.chart_backtest_button)
        self.chart_backtest_button.style().polish(self.chart_backtest_button)
        self.chart_backtest_button.setEnabled(
            state.chart_backtest_active
            or (state.selected_security_id is not None and state.chart.point_count >= 2)
        )

    def _set_combo_data(self, combo: QtWidgets.QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index < 0 or combo.currentIndex() == index:
            return
        combo.blockSignals(True)
        combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _sync_market_and_watchlist(self, state: AppUiState) -> None:
        overview = state.market_overview
        self.market_overview_summary.setText(_market_overview_summary_html(overview))
        self.market_overview_summary.setProperty("stale", overview.is_stale)
        self._set_market_index_items(self.market_indices, overview.indices)
        self._select_list_item(self.market_indices, state.selected_security_id)
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
        self._select_list_item(self.watchlist, state.selected_security_id)
        self._set_list_items(
            self.recent_securities,
            tuple(
                (
                    item.security_id,
                    f"{item.symbol}  {item.name}  {item.asset_type}  {item.exchange}",
                )
                for item in state.recent_securities
            ),
        )
        self._select_list_item(self.recent_securities, state.selected_security_id)

    def _sync_watchlist_buttons(self, state: AppUiState) -> None:
        watchlist_ids = {item.security_id for item in state.watchlist.items}
        selected = state.selected_security_id
        self.add_watchlist_button.setEnabled(selected is not None and selected not in watchlist_ids)
        self.remove_watchlist_button.setEnabled(
            bool(watchlist_ids) and selected is not None and selected in watchlist_ids
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
            item.setToolTip(text.replace("\n", "  "))
            if "\n" in text:
                item.setSizeHint(QtCore.QSize(0, 48))
            widget.addItem(item)
        widget.blockSignals(False)

    def _set_market_index_items(
        self,
        widget: QtWidgets.QListWidget,
        indices: Sequence[MarketIndexPanelState],
    ) -> None:
        widget.blockSignals(True)
        widget.clear()
        for index in indices:
            # Keep an accessible/plain-text representation even when the row
            # uses a custom rich widget for the visible colored values.
            item = QtWidgets.QListWidgetItem(_market_index_item_text(index))
            item.setData(QtCore.Qt.ItemDataRole.UserRole, index.security_id)
            item.setToolTip(_market_index_item_text(index).replace("\n", "  "))
            item.setSizeHint(QtCore.QSize(0, 62))
            widget.addItem(item)
            widget.setItemWidget(item, _market_index_item_widget(index))
        widget.blockSignals(False)

    def _select_list_item(self, widget: QtWidgets.QListWidget, security_id: str | None) -> None:
        if security_id is None:
            return
        widget.blockSignals(True)
        for row in range(widget.count()):
            item = widget.item(row)
            if item.data(QtCore.Qt.ItemDataRole.UserRole) == security_id:
                widget.setCurrentItem(item)
                break
        widget.blockSignals(False)

    def _sync_knowledge(self, state: AppUiState) -> None:
        knowledge = state.knowledge
        if self.knowledge_search.text() != knowledge.query:
            self.knowledge_search.blockSignals(True)
            self.knowledge_search.setText(knowledge.query)
            self.knowledge_search.blockSignals(False)
        self.knowledge_topics.blockSignals(True)
        self.knowledge_topics.clear()
        for topic in knowledge.topics:
            item = QtWidgets.QListWidgetItem(f"{topic.title}  {topic.summary}")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, topic.topic_id)
            self.knowledge_topics.addItem(item)
            if topic.topic_id == knowledge.selected_topic_id:
                self.knowledge_topics.setCurrentItem(item)
        self.knowledge_topics.blockSignals(False)
        self.knowledge_detail.setPlainText(
            f"{knowledge.selected_title}\n\n{knowledge.selected_body}"
        )

    def _build_central_widget(self) -> QtWidgets.QWidget:
        root = QtWidgets.QWidget()
        root.setObjectName("appRoot")
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)

        search_box = QtWidgets.QWidget()
        search_layout = QtWidgets.QVBoxLayout(search_box)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(6)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_results)

        top_bar = QtWidgets.QHBoxLayout()
        top_bar.setSpacing(10)
        top_bar.addWidget(search_box, stretch=2)
        top_bar.addWidget(self._strategy_controls_bar(), stretch=2)
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
        return root

    def _left_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        panel.setObjectName("leftPanel")
        panel.setMinimumWidth(210)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        for title, widget in (
            ("自选列表", self.watchlist),
            ("指数", self.market_indices),
            ("最近访问", self.recent_securities),
        ):
            group = QtWidgets.QGroupBox(title)
            group_layout = QtWidgets.QVBoxLayout(group)
            if title == "自选列表":
                action_layout = QtWidgets.QHBoxLayout()
                action_layout.setContentsMargins(0, 0, 0, 0)
                action_layout.addWidget(self.add_watchlist_button)
                action_layout.addWidget(self.remove_watchlist_button)
                action_layout.addStretch(1)
                group_layout.addLayout(action_layout)
            if title == "指数":
                market_header = QtWidgets.QHBoxLayout()
                market_header.setContentsMargins(0, 0, 0, 0)
                market_header.addWidget(self.market_overview_summary, stretch=1)
                market_header.addWidget(self.refresh_market_button)
                group_layout.addLayout(market_header)
            group_layout.addWidget(widget)
            layout.addWidget(group)
        return panel

    def _center_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        panel.setObjectName("centerPanel")
        panel.setMinimumWidth(560)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(8)
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

    def _strategy_controls_bar(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        panel.setObjectName("strategyControlBar")
        layout = QtWidgets.QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.strategy_horizon_combo)
        layout.addWidget(self.strategy_trade_spin)
        layout.addWidget(self.theme_combo)
        layout.addWidget(self.chart_backtest_button)
        return panel

    def _right_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        panel.setObjectName("rightPanel")
        panel.setMinimumWidth(330)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        for title, label in (
            ("当前策略", self.strategy_panel_label),
            ("预期走势", self.forecast_panel_label),
            ("操作与风险", self.operation_panel_label),
            ("决策证据", self.decision_panel_label),
        ):
            group = QtWidgets.QGroupBox(title)
            group.setMinimumHeight(118)
            group.setMaximumHeight(210)
            group_layout = QtWidgets.QVBoxLayout(group)
            group_layout.setContentsMargins(10, 14, 10, 10)
            group_layout.addWidget(self._panel_scroll_area(label, f"{label.objectName()}Scroll"))
            layout.addWidget(group)
        layout.addStretch(1)
        return panel

    def _placeholder_page(self, title: str) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        label = QtWidgets.QLabel(title)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        return page

    def _backtest_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("盈利验证回测")
        title.setObjectName("backtestTitle")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.strategy_info_button)
        header.addWidget(self.run_backtest_button)
        layout.addLayout(header)

        content = QtWidgets.QHBoxLayout()
        content.setSpacing(12)
        for title_text, label in (
            ("摘要", self.backtest_summary_label),
            ("指标", self.backtest_metrics_label),
            ("证据", self.backtest_notes_label),
        ):
            group = QtWidgets.QGroupBox(title_text)
            group_layout = QtWidgets.QVBoxLayout(group)
            group_layout.addWidget(self._panel_scroll_area(label, f"{label.objectName()}Scroll"))
            content.addWidget(group, stretch=1)
        layout.addLayout(content, stretch=1)
        return page

    def _knowledge_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        left_layout.addWidget(self.knowledge_search)
        left_layout.addWidget(self.knowledge_topics)
        layout.addWidget(left, stretch=1)
        layout.addWidget(self.knowledge_detail, stretch=2)
        return page


def create_application(argv: Sequence[str] | None = None) -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is not None:
        application = cast(QtWidgets.QApplication, app)
    else:
        application = QtWidgets.QApplication(list(argv or sys.argv))
    apply_theme_palette(application, DEFAULT_THEME_MODE)
    return application


def run_gui(argv: Sequence[str] | None = None) -> int:
    app = create_application(argv)
    window = MainWindow(
        ApplicationViewModel(market_data_provider=create_default_market_data_provider())
    )
    window.show()
    return app.exec()


def _strategy_panel_text(state: AppUiState) -> str:
    strategy = state.analysis.strategy
    return _panel_html(
        [
            _field_html("模式", strategy.mode_label, color="#58a6ff"),
            _field_html("策略", strategy.strategy_name, strong=True),
            _field_html("规则", strategy.rule_version),
            _field_html("窗口", strategy.horizon_label),
            _field_html("资产", strategy.asset_scope),
            _field_html("样本", strategy.sample_count),
            _field_html(
                "市场状态",
                strategy.market_regime,
                color=_risk_color(strategy.market_regime),
            ),
            _field_html("原始信号", strategy.raw_signal),
            _chips_html("核心指标", strategy.core_indicators),
            _field_html("模型", strategy.model_version),
        ]
    )


def _market_index_item_text(index: MarketIndexPanelState) -> str:
    if index.latest_value == "--":
        return f"{index.name}\n--  {index.change_pct}"
    return f"{index.name}\n{index.latest_value}  {index.change_pct}"


def _market_index_item_widget(index: MarketIndexPanelState) -> QtWidgets.QWidget:
    color = _change_text_color(index.change_pct)
    widget = QtWidgets.QWidget()
    widget.setObjectName("marketIndexItem")
    layout = QtWidgets.QVBoxLayout(widget)
    layout.setContentsMargins(10, 6, 10, 6)
    layout.setSpacing(2)

    name = QtWidgets.QLabel(html.escape(index.name))
    name.setTextFormat(QtCore.Qt.TextFormat.RichText)
    name.setStyleSheet("background: transparent; color: #dce6f5; font-weight: 700;")

    value = QtWidgets.QLabel(
        f"<span style='color:{color}; font-size:16px; font-weight:800;'>"
        f"{html.escape(index.latest_value)}</span>"
        f"<span style='color:{color}; font-weight:800;'>  "
        f"{html.escape(index.change_pct)}</span>"
    )
    value.setTextFormat(QtCore.Qt.TextFormat.RichText)
    value.setStyleSheet("background: transparent;")

    layout.addWidget(name)
    layout.addWidget(value)
    return widget


def _market_overview_summary_html(overview: MarketOverviewPanelState) -> str:
    rows = [
        ("市场状态", _highlight_value(overview.trend_state, "#f6c453")),
        ("市场广度", _colored_breadth_summary(overview.breadth_summary)),
        ("成交额", _highlight_value(overview.turnover_summary, "#f6c453")),
        ("波动", _highlight_value(overview.volatility_state, "#dce6f5")),
        ("数据", _highlight_value(overview.data_health_text, "#7ee787")),
    ]
    return "<br>".join(
        f"<span style='color:#94a3b8;'>{label}：</span>{value}" for label, value in rows
    )


def _colored_breadth_summary(summary: str) -> str:
    parts = summary.split(" / ")
    if len(parts) != 3:
        return _highlight_value(summary, "#dce6f5")
    up, down, flat = (html.escape(part) for part in parts)
    return (
        f"<span style='color:#ff4d45; font-weight:800;'>{up}</span>"
        " / "
        f"<span style='color:#2fd66f; font-weight:800;'>{down}</span>"
        " / "
        f"<span style='color:#aab4c2; font-weight:700;'>{flat}</span>"
    )


def _highlight_value(value: str, color: str) -> str:
    return f"<span style='color:{color}; font-weight:800;'>{html.escape(value)}</span>"


def _change_text_color(change_text: str) -> str:
    stripped = change_text.strip()
    if stripped.startswith("+"):
        return "#ff4d45"
    if stripped.startswith("-"):
        return "#2fd66f"
    return "#dce6f5"


def _forecast_panel_text(state: AppUiState) -> str:
    forecast = state.analysis.forecast
    return _panel_html(
        [
            _field_html(
                "方向",
                forecast.direction_label,
                color=_direction_color(forecast.direction_label),
            ),
            _field_html("概率", forecast.probability_summary),
            _field_html("收益区间", forecast.expected_return_range),
            _field_html("预期回撤", forecast.expected_drawdown, color="#f6c453"),
            _field_html("校准", forecast.validation_metrics),
            _field_html("说明", forecast.confidence_note),
        ]
    )


def _operation_panel_text(state: AppUiState) -> str:
    operation = state.analysis.operation
    abstain_text = operation.abstain_reason or "--"
    return _panel_html(
        [
            _field_html(
                "策略建议",
                operation.final_signal,
                color=_signal_color(operation.final_signal),
                badge=True,
            ),
            _field_html(
                "等级",
                f"{operation.grade}  {operation.grade_description}",
                color=_grade_color(operation.grade),
            ),
            _field_html("仓位上限", operation.target_position_limit, color="#f6c453"),
            _field_html("有效期", operation.valid_until),
            _field_html(
                "不交易原因",
                abstain_text,
                color="#f6c453" if abstain_text != "--" else None,
            ),
            _brief_list_html("支持因素", operation.positive_drivers, limit=3),
            _brief_list_html("反对/风险", operation.negative_drivers, limit=3),
            _brief_list_html("退出/失效", operation.exit_or_invalidation_conditions, limit=2),
        ]
    )


def _decision_panel_text(state: AppUiState) -> str:
    decision = state.decision
    return _panel_html(
        [
            _field_html(
                "执行状态",
                decision.readiness,
                color=_readiness_color(decision.readiness),
                badge=True,
            ),
            _field_html(
                "门禁后信号",
                decision.final_signal,
                color=_signal_color(decision.final_signal),
            ),
            _field_html("置信度", decision.confidence),
            _field_html("仓位上限", decision.target_position_limit),
            _field_html("历史证据", decision.profitability_summary),
            _field_html("模拟证据", decision.simulation_summary),
            _field_html("门槛", decision.gate_summary, color=_risk_color(decision.gate_summary)),
            _brief_list_html("门槛明细", decision.gate_details, limit=4),
            _brief_list_html("原因", decision.blocking_reasons, limit=3),
            _brief_list_html("边界", decision.caveats, limit=2),
            _field_html("说明", decision.no_profit_guarantee),
        ]
    )


def _backtest_metrics_text(state: AppUiState) -> str:
    backtest = state.backtest
    return "\n".join(
        [
            f"标的：{backtest.security_id}",
            f"期限：{backtest.horizon_label}",
            f"交易上限：{backtest.max_trades_per_year} 次",
            f"阈值：{backtest.selected_threshold}",
            f"净收益：{backtest.total_return}",
            f"年化：{backtest.annualized_return}",
            f"最大回撤：{backtest.max_drawdown}",
            f"相对基准：{backtest.excess_return}",
            f"胜率：{backtest.win_rate}",
            f"交易次数：{backtest.trade_count}",
            f"Brier：{backtest.brier_score}",
            f"可靠性：{backtest.reliability_grade}",
            f"状态：{backtest.status}",
        ]
    )


def _backtest_notes_text(state: AppUiState) -> str:
    backtest = state.backtest
    lines: list[str] = []
    if backtest.trades:
        lines.append("交易流水：")
        lines.extend(_wrap_panel_value(trade) for trade in backtest.trades[:12])
        if len(backtest.trades) > 12:
            lines.append(f"另有 {len(backtest.trades) - 12} 笔交易未显示。")
    else:
        lines.append("交易流水：暂无买卖操作。")
    if backtest.notes:
        lines.append("")
        lines.append("验证说明：")
        lines.extend(f"- {_wrap_panel_value(note)}" for note in backtest.notes)
    return "\n".join(lines)


def _health_banner_text(state: AppUiState) -> str:
    data_health = state.data_health
    if data_health is None or not data_health.issues:
        return state.banner_text
    if _has_online_failure_issue(data_health.issues):
        return f"数据健康：{data_health.status.value}（详情弹窗）"
    return f"数据健康：{data_health.status.value}（详情见状态）"


def _has_online_failure_issue(issues: tuple[str, ...]) -> bool:
    return any(issue.startswith(("联网搜索失败", "联网行情失败")) for issue in issues)


def _panel_html(rows: Sequence[str]) -> str:
    body = "".join(f"<div style='margin:0 0 5px 0;'>{row}</div>" for row in rows if row)
    return (
        "<div style='line-height:1.28; font-size:13px; color:#dce6f5; "
        "white-space:normal;'>"
        f"{body}"
        "</div>"
    )


def _field_html(
    label: str,
    value: str,
    *,
    color: str | None = None,
    strong: bool = False,
    badge: bool = False,
) -> str:
    escaped_label = html.escape(label)
    escaped_value = _escape_panel_text(value)
    weight = "800" if strong or badge else "650"
    value_color = color or "#dce6f5"
    if badge:
        value_html = (
            f"<span style='display:inline-block; padding:2px 7px; border-radius:6px; "
            f"background:{value_color}; color:#071018; font-weight:900;'>{escaped_value}</span>"
        )
    else:
        value_html = (
            f"<span style='color:{value_color}; font-weight:{weight};'>{escaped_value}</span>"
        )
    return f"<span style='color:#8ea0b8;'>{escaped_label}：</span>{value_html}"


def _chips_html(label: str, values: tuple[str, ...]) -> str:
    if not values:
        return _field_html(label, "--")
    chips = " ".join(
        "<span style='display:inline-block; margin:0 3px 3px 0; padding:1px 6px; "
        "border:1px solid #2d3748; border-radius:5px; color:#c9d6e8;'>"
        f"{html.escape(value)}</span>"
        for value in values
    )
    return f"<span style='color:#8ea0b8;'>{html.escape(label)}：</span>{chips}"


def _brief_list_html(title: str, values: tuple[str, ...], *, limit: int) -> str:
    if not values:
        return _field_html(title, "--")
    selected = values[:limit]
    suffix = "" if len(values) <= limit else f"；另{len(values) - limit}项"
    joined = "<br>".join(f"- {_escape_panel_text(value)}" for value in selected)
    if suffix:
        joined = f"{joined}<br><span style='color:#8ea0b8;'>{html.escape(suffix)}</span>"
    return f"<span style='color:#8ea0b8;'>{html.escape(title)}：</span><br>{joined}"


def _escape_panel_text(value: str) -> str:
    return html.escape(_wrap_panel_value(value, width=44)).replace("\n", "<br>")


def _signal_color(signal: str) -> str:
    if signal in {"BUY_CANDIDATE", "ADD_CANDIDATE"}:
        return "#ff4d45"
    if signal in {"SELL", "REDUCE"}:
        return "#2fd66f"
    if signal in {"ABSTAIN", "NOT_ELIGIBLE"}:
        return "#ff7b72"
    if signal in {"WATCH", "RESEARCH_ONLY"}:
        return "#f6c453"
    return "#58a6ff"


def _direction_color(text: str) -> str:
    if "上涨" in text:
        return "#ff4d45"
    if "下跌" in text:
        return "#2fd66f"
    if "不交易" in text or "不明确" in text:
        return "#f6c453"
    return "#58a6ff"


def _risk_color(text: str) -> str:
    if any(token in text for token in ("FAIL", "MISSING", "NEGATIVE", "RISK", "阻断")):
        return "#ff7b72"
    if any(token in text for token in ("WARN", "WATCH", "INSUFFICIENT")):
        return "#f6c453"
    if any(token in text for token in ("PASS", "HEALTHY", "VALIDATED", "全部")):
        return "#7ee787"
    return "#dce6f5"


def _grade_color(grade: str) -> str:
    return {"A": "#7ee787", "B": "#58a6ff", "C": "#f6c453", "N": "#ff7b72"}.get(
        grade,
        "#dce6f5",
    )


def _readiness_color(readiness: str) -> str:
    if readiness == "API_CANDIDATE":
        return "#ff4d45"
    if readiness == "PAPER_READY":
        return "#58a6ff"
    if readiness == "RESEARCH_ONLY":
        return "#f6c453"
    return "#ff7b72"


def _brief_list_text(title: str, values: tuple[str, ...], *, limit: int) -> str:
    if not values:
        return f"{title}：--"
    selected = values[:limit]
    suffix = "" if len(values) <= limit else f"；另{len(values) - limit}项"
    return f"{title}：" + "；\n  ".join(_wrap_panel_value(value) for value in selected) + suffix


def _list_text(title: str, values: tuple[str, ...]) -> str:
    if not values:
        return f"{title}：--"
    return f"{title}：" + "；\n  ".join(_wrap_panel_value(value) for value in values)


def _wrap_panel_value(value: str, *, width: int = 34) -> str:
    if len(value) <= width:
        return value
    chunks = [value[index : index + width] for index in range(0, len(value), width)]
    return "\n  ".join(chunks)


def _load_theme_mode(settings: QtCore.QSettings) -> UiThemeMode:
    return coerce_theme_mode(settings.value(THEME_SETTINGS_KEY), default=DEFAULT_THEME_MODE)


def _theme_label(theme_mode: UiThemeMode) -> str:
    if theme_mode is UiThemeMode.DARK:
        return "黑色主题"
    return "白色主题"


@dataclass(frozen=True, slots=True)
class _StrategyInfo:
    title: str
    subtitle: str
    body: str
    code_path: Path


def _strategy_info_for_state(state: AppUiState) -> _StrategyInfo:
    if state.chart_backtest_active or state.backtest.status == "OPTIMIZED":
        return _StrategyInfo(
            title="图表历史最大利润回测层",
            subtitle=(
                "当前图表显示的是历史最大利润路径：它会在已知完整历史价格之后，"
                "反推最多 N 笔完整买卖能获得的最大收益。"
            ),
            body=(
                "输入：当前标的、策略期限、最多交易次数和图表K线。\n"
                "方法：动态规划比较每一天保持现金、买入持仓或卖出落袋后的资金，"
                "最终选择净值最高的买卖组合。\n"
                "用途：帮助复盘历史最佳买卖点，检查图表和交易流水是否可解释。\n"
                "边界：这是上帝视角历史复盘，不是预测未来的生产策略，"
                "也不会提升真实下单或API执行候选等级。"
            ),
            code_path=_source_file_path("china_quant_platform", "ui", "viewmodel.py"),
        )

    strategy = state.analysis.strategy
    horizon = state.strategy_controls.horizon_label
    max_trades = state.strategy_controls.max_trades_per_year
    strategy_id = strategy.strategy_id if strategy.strategy_id != "--" else "尚未生成策略ID"
    return _StrategyInfo(
        title="盈利验证动量趋势策略",
        subtitle=(
            f"当前策略：{strategy.strategy_name}；ID：{strategy_id}；"
            f"周期：{horizon}；交易上限：{max_trades} 次。"
        ),
        body=(
            "这是一套研究级盈利验证策略，核心目标不是给出收益承诺，"
            "而是检查当前标的在历史样本外是否具备扣除成本后的赚钱证据。\n"
            "方法：结合短期动量、长期趋势、波动率、回撤和持有周期约束，"
            "先在训练/验证区间选择参数阈值，再只在最终样本外区间评估结果。\n"
            "输出：净收益、年化、最大回撤、相对基准、胜率、交易次数、"
            "Brier分数和可靠性等级。\n"
            "边界：缺少模拟盘验证、成本/容量压力或过拟合诊断时，"
            "系统仍会保持 WATCH/RESEARCH_ONLY，不会直接变成真实交易指令。"
        ),
        code_path=_source_file_path("china_quant_platform", "strategies", "profit_validation.py"),
    )


def _source_file_path(*parts: str) -> Path:
    return _project_root() / "src" / Path(*parts)


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parents[1]
    return Path(__file__).resolve().parents[3]


def _open_code_file(path: Path) -> None:
    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))


__all__ = ["MainWindow", "create_application", "run_gui"]
