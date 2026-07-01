"""Market overview and watchlist GUI tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
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
    Bar,
    CorporateAction,
    DataHealth,
    DataHealthStatus,
    FinalSignal,
    FundNav,
    Quote,
    RecordQualityStatus,
    SecurityRef,
)
from china_quant_platform.market import build_market_overview
from china_quant_platform.ui import ApplicationViewModel, MainWindow


def as_of(minute: int = 0) -> datetime:
    return datetime(2026, 6, 29, 15, minute, tzinfo=UTC)


def quote(
    security_id: str,
    latest_price: float,
    previous_close: float,
    *,
    amount: float = 10_000_000,
    source_time: datetime | None = None,
) -> Quote:
    source = source_time or as_of()
    return Quote(
        security_id=security_id,
        latest_price=latest_price,
        previous_close=previous_close,
        open_price=previous_close,
        high_price=max(latest_price, previous_close),
        low_price=min(latest_price, previous_close),
        volume=100_000,
        amount=amount,
        provider="fixture",
        schema_version="v1",
        source_time=source,
        observed_at=source,
        received_at=source + timedelta(seconds=1),
        quality_status=RecordQualityStatus.OK,
    )


def stale_health() -> DataHealth:
    return DataHealth(
        status=DataHealthStatus.STALE,
        block_signal=True,
        as_of=as_of(),
        issues=("stale watchlist quote",),
    )


class InstantIndexProvider:
    provider_id = "instant_index"
    capabilities = ProviderCapabilities(
        provider_id=provider_id,
        supported=frozenset({ProviderCapability.REALTIME_QUOTE}),
    )

    async def search_security(self, keyword: str) -> list[SecurityRef]:
        return []

    async def get_quote(self, security_id: str) -> Quote:
        if security_id == "SSE:000001":
            return quote(security_id, 3_060.0, 3_000.0, amount=100_000_000)
        if security_id == "SZSE:399001":
            return quote(security_id, 10_100.0, 10_000.0, amount=200_000_000)
        return quote(security_id, 100.0, 100.0)

    async def get_bars(self, request: BarsRequest) -> list[Bar]:
        return []

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


class QuoteFailingIndexBarsProvider(InstantIndexProvider):
    async def get_quote(self, security_id: str) -> Quote:
        raise ConnectionError("quote closed connection")

    async def get_bars(self, request: BarsRequest) -> list[Bar]:
        first_end = as_of() - timedelta(days=1)
        second_end = as_of()
        return [
            Bar(
                security_id=request.security_id,
                interval=request.interval,
                start_time=first_end - timedelta(hours=6),
                end_time=first_end,
                trade_date=first_end.date(),
                open_price=99,
                high_price=101,
                low_price=98,
                close_price=100,
                volume=100_000,
                amount=100_000_000,
                adjustment=request.adjustment,
                provider=self.provider_id,
                schema_version="fixture.v1",
                source_time=first_end,
                observed_at=first_end,
                received_at=first_end,
                quality_status=RecordQualityStatus.OK,
            ),
            Bar(
                security_id=request.security_id,
                interval=request.interval,
                start_time=second_end - timedelta(hours=6),
                end_time=second_end,
                trade_date=second_end.date(),
                open_price=100,
                high_price=104,
                low_price=99,
                close_price=102,
                volume=120_000,
                amount=120_000_000,
                adjustment=request.adjustment,
                provider=self.provider_id,
                schema_version="fixture.v1",
                source_time=second_end,
                observed_at=second_end,
                received_at=second_end,
                quality_status=RecordQualityStatus.OK,
            ),
        ]


def test_market_overview_defaults_to_visible_index_placeholders(qtbot: Any) -> None:
    view_model = ApplicationViewModel(clock=as_of)
    window = MainWindow(view_model)
    qtbot.addWidget(window)

    summary = window.findChild(QtWidgets.QLabel, "marketOverviewSummary")
    index_list = window.findChild(QtWidgets.QListWidget, "marketIndexItems")
    refresh_button = window.findChild(QtWidgets.QToolButton, "refreshMarketOverview")
    assert summary is not None
    assert index_list is not None
    assert refresh_button is not None
    assert "等待行情" in summary.text()
    assert index_list.count() == 2
    assert "上证指数" in index_list.item(0).text()
    assert "等待行情" in index_list.item(0).text()


def test_market_overview_auto_refreshes_index_quotes(qtbot: Any) -> None:
    view_model = ApplicationViewModel(
        clock=as_of,
        market_data_provider=InstantIndexProvider(),
    )
    window = MainWindow(view_model)
    qtbot.addWidget(window)

    index_list = window.findChild(QtWidgets.QListWidget, "marketIndexItems")
    summary = window.findChild(QtWidgets.QLabel, "marketOverviewSummary")
    assert index_list is not None
    assert summary is not None

    qtbot.waitUntil(lambda: "3060.00" in index_list.item(0).text(), timeout=1000)

    assert index_list.count() == 2
    assert "上证指数" in index_list.item(0).text()
    assert "+2.00%" in index_list.item(0).text()
    assert "深证成指" in index_list.item(1).text()
    assert "市场广度：上涨2 / 下跌0 / 平盘0" in summary.text()
    assert "数据：HEALTHY" in summary.text()

    index_list.itemActivated.emit(index_list.item(0))
    assert view_model.state.selected_security_id == "SSE:000001"


def test_market_overview_falls_back_to_daily_bars_when_quote_fails(qtbot: Any) -> None:
    view_model = ApplicationViewModel(
        clock=as_of,
        market_data_provider=QuoteFailingIndexBarsProvider(),
    )
    window = MainWindow(view_model)
    qtbot.addWidget(window)

    index_list = window.findChild(QtWidgets.QListWidget, "marketIndexItems")
    assert index_list is not None

    qtbot.waitUntil(lambda: "102.00" in index_list.item(0).text(), timeout=1000)

    assert "+2.00%" in index_list.item(0).text()
    assert view_model.state.market_overview.data_health_text == "HEALTHY"


def test_watchlist_groups_signals_and_stale_state_do_not_change_selection() -> None:
    view_model = ApplicationViewModel(clock=as_of)
    view_model.select_security("SSE:600519")
    selected_security = view_model.state.selected_security_id

    view_model.add_watchlist_item("SSE:510300", group="ETF", pinned=True)
    view_model.add_watchlist_item("SSE:600519", group="核心股票")
    view_model.apply_watchlist_signal(
        "SSE:510300",
        final_signal=FinalSignal.WATCH,
        latest_price=4.12,
        change_pct=0.012,
        data_health=stale_health(),
    )

    assert view_model.state.selected_security_id == selected_security
    assert tuple(group.name for group in view_model.state.watchlist.groups) == ("ETF", "核心股票")
    etf_item = view_model.state.watchlist.groups[0].items[0]
    assert etf_item.security_id == "SSE:510300"
    assert etf_item.final_signal == "WATCH"
    assert etf_item.latest_price == "4.12"
    assert etf_item.change_pct == "1.2%"
    assert etf_item.is_stale is True

    view_model.move_watchlist_item("SSE:510300", group="核心股票", sort_order=0)
    assert len(view_model.state.watchlist.groups) == 1

    view_model.remove_watchlist_item("SSE:510300")
    assert tuple(item.security_id for item in view_model.state.watchlist.items) == ("SSE:600519",)


def test_market_overview_and_watchlist_render_in_left_panel(qtbot: Any) -> None:
    view_model = ApplicationViewModel(clock=as_of)
    window = MainWindow(view_model)
    qtbot.addWidget(window)

    overview = build_market_overview(
        index_quotes=(
            quote("INDEX:000001", 3_060, 3_000, amount=100_000_000),
            quote("INDEX:399001", 10_100, 10_000, amount=200_000_000),
        ),
        constituent_quotes=(
            quote("SSE:600001", 105, 100),
            quote("SSE:600002", 98, 100),
            quote("SSE:600003", 100, 100),
        ),
        as_of=as_of(),
        index_names={"INDEX:000001": "上证指数", "INDEX:399001": "深证成指"},
    )
    view_model.apply_market_overview(overview)
    view_model.add_watchlist_item("SSE:600519", group="核心股票")
    view_model.apply_watchlist_signal(
        "SSE:600519",
        final_signal=FinalSignal.BUY_CANDIDATE,
        latest_price=1680.0,
        change_pct=0.02,
    )

    summary = window.findChild(QtWidgets.QLabel, "marketOverviewSummary")
    index_list = window.findChild(QtWidgets.QListWidget, "marketIndexItems")
    watchlist = window.findChild(QtWidgets.QListWidget, "watchlistItems")
    assert summary is not None
    assert index_list is not None
    assert watchlist is not None
    assert "市场广度：上涨1 / 下跌1 / 平盘1" in summary.text()
    assert "RISK_ON" not in summary.text()
    assert index_list.count() == 2
    assert "上证指数" in index_list.item(0).text()
    assert watchlist.count() == 1
    assert "BUY_CANDIDATE" in watchlist.item(0).text()

    index_list.itemActivated.emit(index_list.item(0))
    assert view_model.state.selected_security_id == "INDEX:000001"


def test_watchlist_buttons_add_and_remove_current_selection(qtbot: Any) -> None:
    view_model = ApplicationViewModel(clock=as_of)
    window = MainWindow(view_model)
    qtbot.addWidget(window)

    add_button = window.findChild(QtWidgets.QToolButton, "addWatchlistItem")
    remove_button = window.findChild(QtWidgets.QToolButton, "removeWatchlistItem")
    watchlist = window.findChild(QtWidgets.QListWidget, "watchlistItems")
    assert add_button is not None
    assert remove_button is not None
    assert watchlist is not None
    assert add_button.isEnabled() is False
    assert remove_button.isEnabled() is False

    view_model.select_security("SSE:600519")
    assert add_button.isEnabled() is True

    qtbot.mouseClick(add_button, QtCore.Qt.MouseButton.LeftButton)
    assert tuple(item.security_id for item in view_model.state.watchlist.items) == ("SSE:600519",)
    assert watchlist.count() == 1
    assert add_button.isEnabled() is False
    assert remove_button.isEnabled() is True

    qtbot.mouseClick(remove_button, QtCore.Qt.MouseButton.LeftButton)
    assert view_model.state.watchlist.items == ()
    assert watchlist.count() == 0


def test_recent_securities_render_and_select_from_left_panel(qtbot: Any) -> None:
    view_model = ApplicationViewModel(clock=as_of)
    window = MainWindow(view_model)
    qtbot.addWidget(window)

    view_model.select_security("SSE:600519")
    view_model.select_security("SSE:510300")

    recent = window.findChild(QtWidgets.QListWidget, "recentSecurityItems")
    assert recent is not None
    assert recent.count() == 2
    assert recent.item(0).data(QtCore.Qt.ItemDataRole.UserRole) == "SSE:510300"
    assert "贵州茅台" in recent.item(1).text()

    recent.itemActivated.emit(recent.item(1))
    assert view_model.state.selected_security_id == "SSE:600519"


def test_stale_market_overview_is_visible_without_replacing_current_selection(qtbot: Any) -> None:
    view_model = ApplicationViewModel(clock=as_of)
    window = MainWindow(view_model)
    qtbot.addWidget(window)
    view_model.select_security("SSE:600519")

    overview = build_market_overview(
        index_quotes=(
            quote(
                "INDEX:000001",
                3_000,
                3_000,
                source_time=as_of() - timedelta(minutes=10),
            ),
        ),
        constituent_quotes=(),
        as_of=as_of(),
    )
    view_model.apply_market_overview(overview)

    summary = window.findChild(QtWidgets.QLabel, "marketOverviewSummary")
    assert summary is not None
    assert view_model.state.selected_security_id == "SSE:600519"
    assert "STALE" in summary.text()
    assert summary.property("stale") is True
