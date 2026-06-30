"""PySide6 app shell and ViewModel tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtWidgets

from china_quant_platform.data import (
    BarsRequest,
    CorporateActionRequest,
    FundNavRequest,
    ProviderCapabilities,
    ProviderCapability,
)
from china_quant_platform.domain import (
    AdjustmentMode,
    AssetType,
    Bar,
    BarInterval,
    CorporateAction,
    Currency,
    DataHealth,
    DataHealthStatus,
    DataStale,
    Exchange,
    FundNav,
    Quote,
    RecordQualityStatus,
    SecurityRef,
    SecurityStatus,
)
from china_quant_platform.ui import (
    ApplicationViewModel,
    ChartRangePreset,
    MainWindow,
    UiRunState,
    UiTaskStatus,
    UiThemeMode,
)


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


class InstantOnlineProvider:
    provider_id = "instant_online"
    capabilities = ProviderCapabilities(
        provider_id=provider_id,
        supported=frozenset(
            {
                ProviderCapability.SECURITY_SEARCH,
                ProviderCapability.REALTIME_QUOTE,
                ProviderCapability.HISTORICAL_BARS,
            }
        ),
    )

    def __init__(self) -> None:
        self.bar_requests: list[BarsRequest] = []

    async def search_security(self, keyword: str) -> list[SecurityRef]:
        if keyword != "513300":
            return []
        return [
            SecurityRef(
                security_id="SSE:513300",
                symbol="513300",
                name="纳斯达克ETF华夏",
                asset_type=AssetType.ETF,
                exchange=Exchange.SSE,
                currency=Currency.CNY,
                listed_date=aware_datetime().date(),
                status_date=aware_datetime().date(),
                status=SecurityStatus.ACTIVE,
            )
        ]

    async def get_quote(self, security_id: str) -> Quote:
        source_time = aware_datetime()
        return Quote(
            security_id=security_id,
            latest_price=2.668,
            previous_close=2.65,
            open_price=2.652,
            high_price=2.671,
            low_price=2.642,
            volume=1_572_452,
            amount=418_140_505,
            provider=self.provider_id,
            schema_version="instant.v1",
            source_time=source_time,
            observed_at=source_time,
            received_at=source_time,
            quality_status=RecordQualityStatus.OK,
        )

    async def get_bars(self, request: BarsRequest) -> list[Bar]:
        self.bar_requests.append(request)
        end_time = datetime(2026, 6, 26, 15, 0, tzinfo=UTC)
        return [
            Bar(
                security_id=request.security_id,
                interval=request.interval,
                start_time=datetime(2026, 6, 26, 9, 30, tzinfo=UTC),
                end_time=end_time,
                trade_date=end_time.date(),
                open_price=2.6,
                high_price=2.7,
                low_price=2.55,
                close_price=2.65,
                volume=1_000_000,
                amount=2_650_000,
                adjustment=request.adjustment,
                provider=self.provider_id,
                schema_version="instant.v1",
                source_time=end_time,
                observed_at=end_time,
                received_at=end_time,
                quality_status=RecordQualityStatus.OK,
            )
        ]

    def subscribe_quotes(self, security_ids: Sequence[str]) -> AsyncIterator[Quote]:
        return self._empty_quote_stream(security_ids)

    async def get_corporate_actions(
        self,
        request: CorporateActionRequest,
    ) -> list[CorporateAction]:
        return []

    async def get_fund_nav(self, request: FundNavRequest) -> list[FundNav]:
        return []

    async def _empty_quote_stream(self, security_ids: Sequence[str]) -> AsyncIterator[Quote]:
        if False:
            yield await self.get_quote(security_ids[0])


class DisconnectingSearchProvider(InstantOnlineProvider):
    async def search_security(self, keyword: str) -> list[SecurityRef]:
        raise ConnectionError("Remote end closed connection without response")


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


def test_online_failure_uses_short_banner_and_popup(qtbot: Any) -> None:
    view_model = ApplicationViewModel(clock=aware_datetime)
    window = MainWindow(view_model)
    qtbot.addWidget(window)

    view_model.apply_data_health(
        DataHealth(
            status=DataHealthStatus.DEGRADED,
            block_signal=True,
            as_of=aware_datetime(),
            issues=(
                "联网搜索失败：Remote end closed connection without response",
                "A股收盘后实时价可能停在收盘价，但历史K线仍应可获取。",
            ),
        )
    )

    banner = window.findChild(QtWidgets.QLabel, "healthBanner")
    assert banner is not None
    assert banner.text() == "数据健康：DEGRADED（详情弹窗）"
    assert "Remote end closed" not in banner.text()
    qtbot.waitUntil(
        lambda: window.findChild(QtWidgets.QMessageBox, "dataHealthPopup") is not None,
        timeout=1000,
    )
    popup = window.findChild(QtWidgets.QMessageBox, "dataHealthPopup")
    assert popup is not None
    assert "Remote end closed" in popup.informativeText()
    popup.close()


def test_settings_button_switches_and_persists_theme(qtbot: Any, tmp_path: Path) -> None:
    settings = QtCore.QSettings(
        str(tmp_path / "theme.ini"),
        QtCore.QSettings.Format.IniFormat,
    )
    view_model = ApplicationViewModel()
    window = MainWindow(view_model, settings=settings)
    qtbot.addWidget(window)

    settings_button = window.findChild(QtWidgets.QToolButton, "settingsButton")
    assert settings_button is not None
    menu = settings_button.menu()
    assert menu is not None
    actions_by_mode = {action.data(): action for action in menu.actions()}

    assert window.theme_mode is UiThemeMode.DARK
    assert window.property("themeMode") == UiThemeMode.DARK.value
    assert window.price_chart.property("themeMode") == UiThemeMode.DARK.value
    assert actions_by_mode[UiThemeMode.DARK.value].isChecked() is True
    assert actions_by_mode[UiThemeMode.LIGHT.value].text() == "白色主题"

    actions_by_mode[UiThemeMode.LIGHT.value].trigger()

    assert window.theme_mode is UiThemeMode.LIGHT
    assert window.property("themeMode") == UiThemeMode.LIGHT.value
    assert window.price_chart.property("themeMode") == UiThemeMode.LIGHT.value
    assert settings.value("appearance/theme") == UiThemeMode.LIGHT.value

    actions_by_mode[UiThemeMode.DARK.value].trigger()

    assert window.theme_mode is UiThemeMode.DARK
    assert settings.value("appearance/theme") == UiThemeMode.DARK.value


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


def test_online_provider_searches_code_and_loads_chart(qtbot: Any) -> None:
    provider = InstantOnlineProvider()
    view_model = ApplicationViewModel(
        clock=aware_datetime,
        market_data_provider=provider,
    )
    window = MainWindow(view_model)
    qtbot.addWidget(window)

    view_model.search_securities("513300")
    qtbot.waitUntil(lambda: bool(view_model.state.search_results), timeout=1000)

    assert view_model.state.search_results[0].security_id == "SSE:513300"

    view_model.confirm_highlighted_search()
    qtbot.waitUntil(
        lambda: (
            view_model.state.data_health is not None and view_model.state.chart.point_count == 2
        ),
        timeout=1000,
    )

    assert view_model.state.selected_security_id == "SSE:513300"
    assert view_model.state.data_health is not None
    assert view_model.state.data_health.status is DataHealthStatus.HEALTHY
    assert view_model.state.run_state is UiRunState.INSUFFICIENT_HISTORY
    assert view_model.state.decision.report is not None
    assert view_model.state.decision.final_signal == "ABSTAIN"
    decision_label = window.findChild(QtWidgets.QLabel, "decisionPanelText")
    assert decision_label is not None
    qtbot.waitUntil(lambda: "原因" in decision_label.text(), timeout=1000)
    assert "历史K线不足" in decision_label.text()
    assert "HEALTHY" in window.health_banner.text()
    assert "2026-06-29" in window.market_time_label.text()
    assert provider.bar_requests[0].interval is BarInterval.DAILY


def test_enter_on_code_loads_chart_when_online_search_disconnects(qtbot: Any) -> None:
    provider = DisconnectingSearchProvider()
    view_model = ApplicationViewModel(
        clock=aware_datetime,
        market_data_provider=provider,
    )
    window = MainWindow(view_model)
    qtbot.addWidget(window)

    search_input = window.findChild(QtWidgets.QLineEdit, "securitySearch")
    assert search_input is not None

    qtbot.keyClicks(search_input, "513300")
    qtbot.keyClick(search_input, QtCore.Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: (
            view_model.state.selected_security_id == "SSE:513300"
            and view_model.state.chart.point_count == 2
        ),
        timeout=1000,
    )

    assert provider.bar_requests[0].security_id == "SSE:513300"
    assert view_model.state.data_health is not None
    assert view_model.state.data_health.status is DataHealthStatus.HEALTHY
    assert "联网搜索失败" not in window.health_banner.text()


def test_chart_controls_reload_online_market_data(qtbot: Any) -> None:
    provider = InstantOnlineProvider()
    view_model = ApplicationViewModel(
        clock=aware_datetime,
        market_data_provider=provider,
    )
    window = MainWindow(view_model)
    qtbot.addWidget(window)

    view_model.search_securities("513300")
    qtbot.waitUntil(lambda: bool(view_model.state.search_results), timeout=1000)
    view_model.confirm_highlighted_search()
    qtbot.waitUntil(lambda: len(provider.bar_requests) >= 2, timeout=1000)

    provider.bar_requests.clear()
    view_model.set_chart_interval(BarInterval.ONE_MINUTE)
    qtbot.waitUntil(
        lambda: (
            len(provider.bar_requests) >= 2
            and view_model.state.task_status is UiTaskStatus.COMPLETED
        ),
        timeout=1000,
    )
    assert provider.bar_requests[0].interval is BarInterval.ONE_MINUTE

    provider.bar_requests.clear()
    view_model.set_chart_range(ChartRangePreset.THREE_MONTHS)
    qtbot.waitUntil(lambda: len(provider.bar_requests) >= 2, timeout=1000)
    assert provider.bar_requests[0].start_time <= aware_datetime() - timedelta(days=100)

    provider.bar_requests.clear()
    view_model.set_chart_adjustment(AdjustmentMode.FORWARD)
    qtbot.waitUntil(lambda: len(provider.bar_requests) >= 2, timeout=1000)
    assert provider.bar_requests[0].adjustment is AdjustmentMode.FORWARD


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
