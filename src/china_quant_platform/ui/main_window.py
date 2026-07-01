"""PySide6 main window shell."""

from __future__ import annotations

import sys
from collections.abc import Sequence
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
        self.setWindowTitle("中国股票与基金量化分析平台")
        self.resize(1440, 900)
        self.setObjectName("mainWindow")

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
        self.settings_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)

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

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("workspaceTabs")
        for title in ("市场", "策略", "回测", "模拟账户", "风险", "知识中心"):
            page = self._knowledge_page() if title == "知识中心" else self._placeholder_page(title)
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
                self.search_timer.stop()
                query = self.search_input.text().strip()
                if query and query != self.view_model.state.search_query:
                    self.view_model.search_securities(query)
                self.view_model.confirm_highlighted_search()
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
        label.setMinimumHeight(0)
        label.setContentsMargins(0, 0, 4, 0)
        label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.MinimumExpanding,
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
                (index.security_id, _market_index_item_text(index)) for index in overview.indices
            ),
        )
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
            group.setMinimumHeight(160)
            group_layout = QtWidgets.QVBoxLayout(group)
            group_layout.addWidget(self._panel_scroll_area(label, f"{label.objectName()}Scroll"))
            layout.addWidget(group, stretch=1)
        return panel

    def _placeholder_page(self, title: str) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        label = QtWidgets.QLabel(title)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
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
    lines = [
        f"策略：{strategy.strategy_name}",
        f"ID：{_wrap_panel_value(strategy.strategy_id)}",
        f"版本：{_wrap_panel_value(strategy.strategy_version)}",
        f"周期：{strategy.horizon_label}",
        f"市场状态：{strategy.market_regime}",
        f"原始信号：{strategy.raw_signal}",
        f"模型：{_wrap_panel_value(strategy.model_version)}",
        f"规则：{_wrap_panel_value(strategy.rule_version)}",
        f"快照：{_wrap_panel_value(strategy.data_snapshot_id)}",
        _list_text("适用条件", strategy.applicable_conditions),
        _list_text("失效条件", strategy.invalidation_conditions),
    ]
    return "\n".join(lines)


def _market_index_item_text(index: MarketIndexPanelState) -> str:
    if index.latest_value == "--":
        return f"{index.name}\n--  {index.change_pct}"
    return f"{index.name}\n{index.latest_value}  {index.change_pct}"


def _forecast_panel_text(state: AppUiState) -> str:
    forecast = state.analysis.forecast
    return "\n".join(
        [
            f"方向：{forecast.direction_label}",
            f"概率：{forecast.probability_summary}",
            f"收益区间：{forecast.expected_return_range}",
            f"预期回撤：{forecast.expected_drawdown}",
            f"校准/说明：{forecast.confidence_note}",
            f"模型：{_wrap_panel_value(forecast.model_version)}",
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


def _decision_panel_text(state: AppUiState) -> str:
    decision = state.decision
    lines = [
        f"最终建议：{decision.final_signal}",
        f"执行候选：{decision.readiness}",
        f"置信度：{decision.confidence}",
        f"仓位上限：{decision.target_position_limit}",
        f"历史证据：{decision.profitability_summary}",
        f"模拟证据：{decision.simulation_summary}",
        f"门槛：{decision.gate_summary}",
        _brief_list_text("原因", decision.blocking_reasons, limit=3),
        _brief_list_text("边界", decision.caveats, limit=2),
        f"说明：{decision.no_profit_guarantee}",
    ]
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


__all__ = ["MainWindow", "create_application", "run_gui"]
