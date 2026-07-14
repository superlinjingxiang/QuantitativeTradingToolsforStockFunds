"""Qt ViewModel and cancellable task shell."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from PySide6 import QtCore

from china_quant_platform.data import (
    BarsRequest,
    MarketDataProvider,
    SecurityMasterService,
    SecuritySearchResult,
)
from china_quant_platform.decision import DecisionReport
from china_quant_platform.decision.hub import DecisionHub
from china_quant_platform.decision.models import DecisionRequest, ProfitabilityEvidence
from china_quant_platform.domain import (
    AbstainReason,
    AdjustmentMode,
    AnalysisReport,
    AssetType,
    Bar,
    BarInterval,
    Currency,
    DataHealth,
    DataHealthStatus,
    DataUnavailable,
    DirectionProbabilities,
    DomainError,
    Exchange,
    FinalSignal,
    Quote,
    SecurityRef,
    SecurityStatus,
)
from china_quant_platform.forecasting import IntervalForecastResult, forecast_interval_from_bars
from china_quant_platform.knowledge import KnowledgeCenter
from china_quant_platform.market import MarketOverview, build_market_overview
from china_quant_platform.strategies.profit_validation import (
    HorizonPreset,
    MarketRegimeGateStatus,
    ProfitBacktestResult,
    ProfitSeekingConfig,
    ProfitValidationStatus,
    horizon_parameters,
    profit_strategy_config,
    run_profit_strategy_backtest,
)
from china_quant_platform.ui.state import (
    AnalysisPanelState,
    AppUiState,
    BacktestPanelState,
    ChartOverlay,
    ChartPointState,
    ChartRangePreset,
    ChartSignalAction,
    ChartSignalMarkerState,
    ChartState,
    DecisionPanelState,
    KnowledgeCenterState,
    MarketOverviewPanelState,
    RecentSecurityState,
    SearchCandidateState,
    StrategyControlState,
    StrategyMode,
    UiErrorState,
    UiRunState,
    UiTaskStatus,
    WatchlistGroupState,
    WatchlistItemState,
    WatchlistPanelState,
    run_state_for_error,
    run_state_for_health,
)


class CancellableQtTask(QtCore.QObject):
    """Small non-blocking task handle used by the GUI shell and tests."""

    finished = QtCore.Signal(object)
    failed = QtCore.Signal(object)
    cancelled = QtCore.Signal()

    def __init__(
        self,
        *,
        name: str,
        delay_ms: int,
        generation: int = 0,
        result_factory: Callable[[], object] | None = None,
        error_factory: Callable[[], BaseException] | None = None,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.name = name
        self.generation = generation
        self._result_factory = result_factory or (lambda: None)
        self._error_factory = error_factory
        self._cancelled = False
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._finish)

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def start(self) -> None:
        self._timer.start()

    @QtCore.Slot()
    def cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        self._timer.stop()
        self.cancelled.emit()

    @QtCore.Slot()
    def _finish(self) -> None:
        if self._cancelled:
            self.cancelled.emit()
            return
        if self._error_factory is not None:
            self.failed.emit(self._error_factory())
            return
        self.finished.emit(self._result_factory())


_BackgroundJobKind = Literal["search", "security_data", "market_overview"]

_DEFAULT_MARKET_INDEX_NAMES: dict[str, str] = {
    "SSE:000001": "上证指数",
    "SZSE:399001": "深证成指",
}
_DEFAULT_MARKET_INDEX_IDS = tuple(_DEFAULT_MARKET_INDEX_NAMES)
_MARKET_OVERVIEW_STALE_AFTER_SECONDS = 7 * 24 * 60 * 60


@dataclass(slots=True)
class _BackgroundJob:
    kind: _BackgroundJobKind
    token: int
    generation: int
    future: Future[object]


@dataclass(frozen=True, slots=True)
class _OnlineSecurityData:
    security_id: str
    bars: tuple[Bar, ...]
    decision_bars: tuple[Bar, ...]
    market_regime_bars: tuple[Bar, ...]
    quote: Quote
    data_health: DataHealth


@dataclass(frozen=True, slots=True)
class _OnlineMarketOverviewData:
    overview: MarketOverview
    failures: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _OptimalChartTrade:
    entry_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    net_return: float


@dataclass(frozen=True, slots=True)
class _OptimalChartBacktest:
    points: tuple[ChartPointState, ...]
    signals: tuple[ChartSignalMarkerState, ...]
    panel: BacktestPanelState


@dataclass(frozen=True, slots=True)
class _ChartBacktestSnapshot:
    security_id: str
    chart: ChartState
    backtest: BacktestPanelState
    run_state: UiRunState
    task_status: UiTaskStatus
    active_task_name: str | None
    latest_error: UiErrorState | None


class ApplicationViewModel(QtCore.QObject):
    state_changed = QtCore.Signal(object)

    def __init__(
        self,
        parent: QtCore.QObject | None = None,
        *,
        security_master: SecurityMasterService | None = None,
        market_data_provider: MarketDataProvider | None = None,
        knowledge_center: KnowledgeCenter | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(parent)
        self._active_task: CancellableQtTask | None = None
        self._security_master = security_master or build_demo_security_master()
        self._market_data_provider = market_data_provider
        self._knowledge_center = knowledge_center or KnowledgeCenter()
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="market-data")
        self._background_jobs: list[_BackgroundJob] = []
        self._background_poll_timer = QtCore.QTimer(self)
        self._background_poll_timer.setInterval(50)
        self._background_poll_timer.timeout.connect(self._drain_background_jobs)
        self._search_token = 0
        self._security_data_token = 0
        self._market_overview_token = 0
        self._latest_decision_bars_by_security: dict[str, tuple[Bar, ...]] = {}
        self._chart_backtest_snapshot: _ChartBacktestSnapshot | None = None
        self._state = AppUiState(
            knowledge=KnowledgeCenterState.from_topics(self._knowledge_center.list_topics())
        )
        self.refresh_market_overview()

    @property
    def state(self) -> AppUiState:
        return self._state

    @property
    def active_task(self) -> CancellableQtTask | None:
        return self._active_task

    def search_securities(self, query: str, *, as_of: date | None = None) -> None:
        stripped_query = query.strip()
        self._search_token += 1
        search_token = self._search_token
        if not stripped_query:
            self._set_state(
                self._state.model_copy(
                    update={
                        "search_query": "",
                        "search_results": (),
                        "highlighted_search_index": None,
                        "run_state": UiRunState.IDLE,
                    }
                )
            )
            return

        results = self._security_master.search(
            stripped_query,
            as_of=as_of,
            limit=10,
            include_inactive=True,
        )
        candidates = tuple(SearchCandidateState.from_search_result(result) for result in results)
        search_date = as_of or self._clock().date()
        if not candidates:
            fallback_security = _fallback_security_from_query(stripped_query, as_of=search_date)
            if fallback_security is not None:
                self._security_master.upsert_security(fallback_security)
                candidates = (
                    SearchCandidateState.from_search_result(
                        SecuritySearchResult(
                            query=stripped_query,
                            security=fallback_security,
                            score=0.72,
                            matched_fields=("code-fallback",),
                        )
                    ),
                )
        self._set_state(
            self._state.model_copy(
                update={
                    "search_query": stripped_query,
                    "search_results": candidates,
                    "highlighted_search_index": 0 if candidates else None,
                    "run_state": UiRunState.SEARCHING,
                    "latest_error": None,
                }
            )
        )
        if self._market_data_provider is not None and (
            not candidates or _looks_like_security_code_or_symbol(stripped_query)
        ):
            self._start_online_security_search(stripped_query, search_token)

    def move_search_highlight(self, delta: int) -> None:
        if not self._state.search_results:
            return
        current = self._state.highlighted_search_index
        next_index = 0 if current is None else (current + delta) % len(self._state.search_results)
        self._set_state(self._state.model_copy(update={"highlighted_search_index": next_index}))

    def confirm_highlighted_search(self) -> None:
        index = self._state.highlighted_search_index
        if index is None or index >= len(self._state.search_results):
            return
        self.select_security(self._state.search_results[index].security_id)

    def search_knowledge(self, query: str) -> None:
        stripped_query = query.strip()
        topics = self._knowledge_center.search(stripped_query)
        self._set_state(
            self._state.model_copy(
                update={
                    "knowledge": KnowledgeCenterState.from_topics(
                        topics,
                        query=stripped_query,
                    )
                }
            )
        )

    def select_knowledge_topic(self, topic_id: str) -> None:
        topic = self._knowledge_center.get_topic(topic_id)
        topics = self._knowledge_center.search(self._state.knowledge.query)
        self._set_state(
            self._state.model_copy(
                update={
                    "knowledge": KnowledgeCenterState.from_topics(
                        topics,
                        query=self._state.knowledge.query,
                        selected=topic,
                    )
                }
            )
        )

    def contextual_help(self, term: str) -> str | None:
        topic = self._knowledge_center.contextual_help(term)
        if topic is None:
            return None
        return KnowledgeCenterState.from_topics((topic,), selected=topic).selected_body

    def _recent_security_states(
        self,
        *,
        as_of: date | None = None,
        limit: int = 8,
    ) -> tuple[RecentSecurityState, ...]:
        return tuple(
            RecentSecurityState.from_security_ref(security)
            for security in self._security_master.recent_searches(as_of=as_of, limit=limit)
        )

    def select_security(self, security_id: str) -> None:
        if self._active_task is not None:
            self.cancel_active_task()
        if security_id == self._state.selected_security_id:
            if self._state.task_status is not UiTaskStatus.RUNNING:
                self._reload_selected_security_data()
            return

        selected_at = self._clock()
        security = self._security_master.select_security(
            security_id,
            selected_at=selected_at,
            as_of=selected_at.date(),
        )
        self._chart_backtest_snapshot = None
        next_generation = self._state.selection_generation + 1
        self._set_state(
            self._state.model_copy(
                update={
                    "selection_generation": next_generation,
                    "selected_security_id": security.security_id,
                    "search_query": "",
                    "search_results": (),
                    "highlighted_search_index": None,
                    "recent_securities": self._recent_security_states(as_of=selected_at.date()),
                    "chart": self._state.chart.model_copy(
                        update={
                            "points": (),
                            "signals": (),
                            "update_count": self._state.chart.update_count + 1,
                            "realtime_update_count": 0,
                        }
                    ),
                    "analysis": AnalysisPanelState(),
                    "decision": DecisionPanelState(),
                    "backtest": BacktestPanelState(),
                    "chart_backtest_active": False,
                    "run_state": UiRunState.LOADING_CACHE_HISTORY,
                    "task_status": UiTaskStatus.IDLE,
                    "active_task_name": None,
                    "latest_error": None,
                }
            )
        )
        if self._market_data_provider is not None:
            self._start_online_security_data_load(security.security_id, next_generation)

    def set_chart_interval(self, interval: BarInterval) -> None:
        if self._state.chart_backtest_active:
            self._restore_chart_backtest_layer()
        if self._state.chart.interval == interval:
            return
        self._set_state(
            self._state.model_copy(
                update={"chart": self._state.chart.model_copy(update={"interval": interval})}
            )
        )
        self._reload_selected_security_data()

    def set_chart_adjustment(self, adjustment: AdjustmentMode) -> None:
        if self._state.chart_backtest_active:
            self._restore_chart_backtest_layer()
        if self._state.chart.adjustment == adjustment:
            return
        self._set_state(
            self._state.model_copy(
                update={"chart": self._state.chart.model_copy(update={"adjustment": adjustment})}
            )
        )
        self._reload_selected_security_data()

    def set_chart_range(self, range_preset: ChartRangePreset) -> None:
        if self._state.chart_backtest_active:
            self._restore_chart_backtest_layer()
        if self._state.chart.range_preset == range_preset:
            return
        self._set_state(
            self._state.model_copy(
                update={
                    "chart": self._state.chart.model_copy(update={"range_preset": range_preset})
                }
            )
        )
        self._reload_selected_security_data()

    def set_chart_overlay_enabled(self, overlay: ChartOverlay, enabled: bool) -> None:
        if overlay is ChartOverlay.SIGNALS:
            if enabled and not self._state.chart_backtest_active:
                self.run_chart_profit_backtest()
                return
            if not enabled and self._state.chart_backtest_active:
                self._restore_chart_backtest_layer()
                return
        overlays = set(self._state.chart.overlays)
        if enabled:
            overlays.add(overlay)
        else:
            overlays.discard(overlay)
        self._set_state(
            self._state.model_copy(
                update={
                    "chart": self._state.chart.model_copy(update={"overlays": frozenset(overlays)})
                }
            )
        )

    def set_strategy_horizon(self, horizon: HorizonPreset) -> None:
        if self._state.chart_backtest_active:
            self._restore_chart_backtest_layer()
        if self._state.strategy_controls.horizon == horizon:
            return
        self._set_state(
            self._state.model_copy(
                update={
                    "strategy_controls": self._state.strategy_controls.model_copy(
                        update={"horizon": horizon}
                    ),
                    "analysis": AnalysisPanelState(),
                    "decision": DecisionPanelState(),
                    "backtest": BacktestPanelState(summary="策略参数已修改，等待重新回测。"),
                }
            )
        )
        self._reload_selected_security_data()

    def set_strategy_mode(self, mode: StrategyMode) -> None:
        if self._state.chart_backtest_active:
            self._restore_chart_backtest_layer()
        controls = StrategyControlState.for_mode(mode)
        if self._state.strategy_controls == controls:
            return
        self._set_state(
            self._state.model_copy(
                update={
                    "strategy_controls": controls,
                    "analysis": AnalysisPanelState(),
                    "decision": DecisionPanelState(),
                    "backtest": BacktestPanelState(summary="策略模式已修改，等待重新回测。"),
                }
            )
        )
        self._reload_selected_security_data()

    def set_strategy_max_trades_per_year(self, max_trades_per_year: int) -> None:
        if self._state.chart_backtest_active:
            self._restore_chart_backtest_layer()
        normalized = max(1, min(max_trades_per_year, 60))
        if self._state.strategy_controls.max_trades_per_year == normalized:
            return
        self._set_state(
            self._state.model_copy(
                update={
                    "strategy_controls": self._state.strategy_controls.model_copy(
                        update={"max_trades_per_year": normalized}
                    ),
                    "analysis": AnalysisPanelState(),
                    "decision": DecisionPanelState(),
                    "backtest": BacktestPanelState(summary="策略参数已修改，等待重新回测。"),
                }
            )
        )
        self._reload_selected_security_data()

    def run_current_backtest(self) -> None:
        if self._state.selected_security_id is None:
            self._set_state(
                self._state.model_copy(
                    update={"backtest": BacktestPanelState(summary="请先选择一个标的。")}
                )
            )
            return
        self._set_state(
            self._state.model_copy(
                update={
                    "run_state": UiRunState.BACKTEST_RUNNING,
                    "task_status": UiTaskStatus.RUNNING,
                    "active_task_name": "策略回测",
                    "backtest": BacktestPanelState(summary="正在运行策略回测..."),
                }
            )
        )
        self._reload_selected_security_data()

    def run_chart_profit_backtest(self) -> None:
        if self._state.chart_backtest_active:
            self._restore_chart_backtest_layer()
            return
        security_id = self._state.selected_security_id
        if security_id is None:
            self._set_state(
                self._state.model_copy(
                    update={"backtest": BacktestPanelState(summary="请先选择一个标的。")}
                )
            )
            return
        source_bars = self._latest_decision_bars_by_security.get(security_id, ())
        self._chart_backtest_snapshot = _ChartBacktestSnapshot(
            security_id=security_id,
            chart=self._state.chart,
            backtest=self._state.backtest,
            run_state=self._state.run_state,
            task_status=self._state.task_status,
            active_task_name=self._state.active_task_name,
            latest_error=self._state.latest_error,
        )
        result = _run_optimal_chart_backtest(
            security_id=security_id,
            bars=source_bars,
            fallback_points=self._state.chart.points,
            horizon=self._state.strategy_controls.horizon,
            max_trades=self._state.strategy_controls.max_trades_per_year,
        )
        if result is None:
            self._chart_backtest_snapshot = None
            self._set_state(
                self._state.model_copy(
                    update={
                        "backtest": BacktestPanelState(
                            summary="当前图表数据不足，至少需要两个价格点才能回测。"
                        )
                    }
                )
            )
            return
        self._set_state(
            self._state.model_copy(
                update={
                    "run_state": UiRunState.BACKTEST_COMPLETED,
                    "task_status": UiTaskStatus.COMPLETED,
                    "active_task_name": "图表回测",
                    "backtest": result.panel,
                    "chart_backtest_active": True,
                    "chart": self._state.chart.model_copy(
                        update={
                            "signals": result.signals,
                            "overlays": frozenset(
                                {
                                    *self._state.chart.overlays,
                                    ChartOverlay.SIGNALS,
                                }
                            ),
                            "update_count": self._state.chart.update_count + 1,
                        }
                    ),
                    "latest_error": None,
                }
            )
        )

    def _restore_chart_backtest_layer(self) -> None:
        snapshot = self._chart_backtest_snapshot
        self._chart_backtest_snapshot = None
        if snapshot is None or snapshot.security_id != self._state.selected_security_id:
            self._set_state(self._state.model_copy(update={"chart_backtest_active": False}))
            return
        self._set_state(
            self._state.model_copy(
                update={
                    "chart": snapshot.chart,
                    "backtest": snapshot.backtest,
                    "run_state": snapshot.run_state,
                    "task_status": snapshot.task_status,
                    "active_task_name": snapshot.active_task_name,
                    "latest_error": snapshot.latest_error,
                    "chart_backtest_active": False,
                }
            )
        )

    def load_chart_bars(self, bars: tuple[Bar, ...], *, generation: int | None = None) -> None:
        if self._is_stale_generation(generation):
            return

        points = tuple(
            ChartPointState.from_bar(bar)
            for bar in sorted(bars, key=lambda item: item.end_time)
            if self._state.selected_security_id is None
            or bar.security_id == self._state.selected_security_id
        )
        self._set_state(
            self._state.model_copy(
                update={
                    "chart": self._state.chart.model_copy(
                        update={
                            "points": points,
                            "update_count": self._state.chart.update_count + 1,
                        }
                    ),
                    "run_state": UiRunState.REALTIME_RUNNING if points else self._state.run_state,
                }
            )
        )

    def apply_realtime_quote(self, quote: Quote, *, generation: int | None = None) -> None:
        if self._is_stale_generation(generation):
            return
        if (
            self._state.selected_security_id is not None
            and quote.security_id != self._state.selected_security_id
        ):
            return

        point = ChartPointState.from_quote(quote)
        points = list(self._state.chart.points)
        if points and points[-1].time_label == point.time_label:
            points[-1] = point
        else:
            points.append(point)

        self._set_state(
            self._state.model_copy(
                update={
                    "chart": self._state.chart.model_copy(
                        update={
                            "points": tuple(points),
                            "update_count": self._state.chart.update_count + 1,
                            "realtime_update_count": (self._state.chart.realtime_update_count + 1),
                        }
                    ),
                    "run_state": UiRunState.REALTIME_RUNNING,
                }
            )
        )

    def apply_data_health(self, data_health: DataHealth) -> None:
        self._set_state(
            self._state.model_copy(
                update={
                    "data_health": data_health,
                    "run_state": run_state_for_health(data_health),
                    "latest_error": None,
                }
            )
        )

    def apply_market_overview(
        self,
        overview: MarketOverview,
        *,
        generation: int | None = None,
    ) -> None:
        if self._is_stale_generation(generation):
            return
        self._set_state(
            self._state.model_copy(
                update={"market_overview": self._state.market_overview.from_overview(overview)}
            )
        )

    def refresh_market_overview(self) -> None:
        provider = self._market_data_provider
        if provider is None:
            return

        self._market_overview_token += 1
        token = self._market_overview_token
        self._set_state(
            self._state.model_copy(update={"market_overview": MarketOverviewPanelState.loading()})
        )

        def quote_operation(security_id: str) -> Callable[[], Coroutine[Any, Any, Quote]]:
            return lambda: _load_market_index_quote(
                provider=provider,
                security_id=security_id,
                as_of=self._clock(),
            )

        async def load() -> _OnlineMarketOverviewData:
            quote_results = await asyncio.gather(
                *(
                    _run_provider_operation(quote_operation(security_id))
                    for security_id in _DEFAULT_MARKET_INDEX_IDS
                ),
                return_exceptions=True,
            )
            quotes = tuple(result for result in quote_results if isinstance(result, Quote))
            failures = tuple(
                f"{security_id}: {_short_error(result)}"
                for security_id, result in zip(
                    _DEFAULT_MARKET_INDEX_IDS,
                    quote_results,
                    strict=True,
                )
                if isinstance(result, BaseException)
            )
            overview = build_market_overview(
                index_quotes=quotes,
                constituent_quotes=quotes,
                as_of=self._clock(),
                index_names=_DEFAULT_MARKET_INDEX_NAMES,
                stale_after_seconds=_MARKET_OVERVIEW_STALE_AFTER_SECONDS,
            )
            if failures and quotes:
                overview = overview.model_copy(
                    update={
                        "data_health": DataHealth(
                            status=DataHealthStatus.DEGRADED,
                            block_signal=False,
                            as_of=self._clock(),
                            issues=failures,
                        )
                    }
                )
            return _OnlineMarketOverviewData(overview=overview, failures=failures)

        self._submit_background_job(
            kind="market_overview",
            token=token,
            generation=self._state.selection_generation,
            func=lambda: asyncio.run(load()),
        )

    def add_watchlist_item(
        self,
        security_id: str,
        *,
        group: str = "默认",
        pinned: bool = False,
    ) -> None:
        selected_at = self._clock()
        security = self._security_master.select_security(
            security_id,
            selected_at=selected_at,
            as_of=selected_at.date(),
        )
        current_items = {item.security_id: item for item in self._state.watchlist.items}
        existing = current_items.get(security.security_id)
        if existing is not None:
            current_items[security.security_id] = existing.model_copy(
                update={"group": group, "pinned": pinned or existing.pinned}
            )
        else:
            current_items[security.security_id] = WatchlistItemState(
                security_id=security.security_id,
                symbol=security.symbol,
                name=security.name,
                group=group,
                sort_order=_next_sort_order(self._state.watchlist.items, group),
                pinned=pinned,
            )
        self._set_watchlist_items(tuple(current_items.values()))
        self._set_state(
            self._state.model_copy(
                update={"recent_securities": self._recent_security_states(as_of=selected_at.date())}
            )
        )

    def remove_watchlist_item(self, security_id: str) -> None:
        items = tuple(
            item for item in self._state.watchlist.items if item.security_id != security_id
        )
        self._set_watchlist_items(items)

    def move_watchlist_item(
        self,
        security_id: str,
        *,
        group: str,
        sort_order: int | None = None,
    ) -> None:
        items = tuple(
            item.model_copy(
                update={
                    "group": group,
                    "sort_order": item.sort_order if sort_order is None else sort_order,
                }
            )
            if item.security_id == security_id
            else item
            for item in self._state.watchlist.items
        )
        self._set_watchlist_items(items)

    def apply_watchlist_signal(
        self,
        security_id: str,
        *,
        final_signal: FinalSignal,
        latest_price: float | None = None,
        change_pct: float | None = None,
        data_health: DataHealth | None = None,
    ) -> None:
        items = tuple(
            _watchlist_item_with_signal(
                item,
                final_signal=final_signal,
                latest_price=latest_price,
                change_pct=change_pct,
                data_health=data_health,
            )
            if item.security_id == security_id
            else item
            for item in self._state.watchlist.items
        )
        self._set_watchlist_items(items)

    def apply_watchlist_market_snapshot(
        self,
        security_id: str,
        *,
        latest_price: float | None = None,
        change_pct: float | None = None,
        data_health: DataHealth | None = None,
    ) -> None:
        if not any(item.security_id == security_id for item in self._state.watchlist.items):
            return
        items = tuple(
            _watchlist_item_with_market_snapshot(
                item,
                latest_price=latest_price,
                change_pct=change_pct,
                data_health=data_health,
            )
            if item.security_id == security_id
            else item
            for item in self._state.watchlist.items
        )
        self._set_watchlist_items(items)

    def select_watchlist_item(self, security_id: str) -> None:
        if any(item.security_id == security_id for item in self._state.watchlist.items):
            self.select_security(security_id)

    def apply_analysis_report(
        self,
        report: AnalysisReport,
        *,
        generation: int | None = None,
        strategy_name: str | None = None,
        strategy_summary: str | None = None,
        applicable_conditions: tuple[str, ...] = (),
    ) -> None:
        if self._is_stale_generation(generation):
            return
        if (
            self._state.selected_security_id is not None
            and report.security_id != self._state.selected_security_id
        ):
            return

        self._set_state(
            self._state.model_copy(
                update={
                    "data_health": report.data_health,
                    "analysis": AnalysisPanelState.from_report(
                        report,
                        strategy_name=strategy_name,
                        strategy_summary=strategy_summary,
                        applicable_conditions=applicable_conditions,
                    ),
                    "run_state": _run_state_for_analysis_report(report),
                    "latest_error": None,
                }
            )
        )

    def apply_decision_report(
        self,
        report: DecisionReport,
        *,
        generation: int | None = None,
    ) -> None:
        if self._is_stale_generation(generation):
            return
        if (
            self._state.selected_security_id is not None
            and report.request.security_id != self._state.selected_security_id
        ):
            return

        self._set_state(
            self._state.model_copy(
                update={
                    "data_health": report.analysis_report.data_health,
                    "analysis": AnalysisPanelState.from_report(report.analysis_report),
                    "decision": DecisionPanelState.from_report(report),
                    "run_state": _run_state_for_analysis_report(report.analysis_report),
                    "latest_error": None,
                }
            )
        )

    def apply_domain_error(self, error: DomainError) -> None:
        self._set_state(
            self._state.model_copy(
                update={
                    "run_state": run_state_for_error(error.kind),
                    "latest_error": UiErrorState(
                        kind=error.kind,
                        user_message=error.user_message,
                        engineering_message=error.engineering_message,
                        retryable=error.retryable,
                        blocks_signal=error.blocks_signal,
                    ),
                }
            )
        )

    def start_demo_task(
        self,
        *,
        name: str = "demo",
        delay_ms: int = 100,
        fail_with: Callable[[], DomainError] | None = None,
    ) -> CancellableQtTask:
        if self._active_task is not None:
            self.cancel_active_task()

        task = CancellableQtTask(
            name=name,
            delay_ms=delay_ms,
            generation=self._state.selection_generation,
            result_factory=lambda: name,
            error_factory=fail_with,
            parent=self,
        )
        generation = task.generation
        task.finished.connect(lambda _result: self._complete_task(name, generation))
        task.cancelled.connect(lambda: self._mark_task_cancelled(name, generation))
        task.failed.connect(lambda error: self._fail_task(error, generation))
        self._active_task = task
        self._set_state(
            self._state.model_copy(
                update={
                    "run_state": UiRunState.BACKTEST_RUNNING,
                    "task_status": UiTaskStatus.RUNNING,
                    "active_task_name": name,
                    "latest_error": None,
                }
            )
        )
        task.start()
        return task

    def cancel_active_task(self) -> None:
        if self._active_task is None:
            self._cancel_background_security_data()
            return
        self._set_state(
            self._state.model_copy(
                update={
                    "run_state": UiRunState.BACKTEST_CANCELLING,
                    "task_status": UiTaskStatus.CANCELLING,
                }
            )
        )
        self._active_task.cancel()

    def shutdown(self) -> None:
        self._background_poll_timer.stop()
        for job in self._background_jobs:
            job.future.cancel()
        self._background_jobs = []
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _start_online_security_search(self, query: str, token: int) -> None:
        provider = self._market_data_provider
        if provider is None:
            return

        def search() -> object:
            return asyncio.run(provider.search_security(query))

        self._submit_background_job(
            kind="search",
            token=token,
            generation=self._state.selection_generation,
            func=search,
        )

    def _start_online_security_data_load(self, security_id: str, generation: int) -> None:
        provider = self._market_data_provider
        if provider is None:
            return

        self._security_data_token += 1
        data_token = self._security_data_token
        interval = self._state.chart.interval
        adjustment = self._state.chart.adjustment
        range_preset = self._state.chart.range_preset
        end_time = self._clock()
        start_time = _range_start(end_time, range_preset)
        request = BarsRequest(
            security_id=security_id,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
            adjustment=adjustment,
        )
        self._set_state(
            self._state.model_copy(
                update={
                    "run_state": UiRunState.FETCHING_REMOTE_HISTORY,
                    "task_status": UiTaskStatus.RUNNING,
                    "active_task_name": "联网行情",
                }
            )
        )

        async def load() -> _OnlineSecurityData:
            decision_start_time = _strategy_decision_start_time(
                end_time,
                self._state.strategy_controls.horizon,
            )
            decision_request = BarsRequest(
                security_id=security_id,
                interval=BarInterval.DAILY,
                start_time=decision_start_time,
                end_time=end_time,
                adjustment=AdjustmentMode.FORWARD,
            )
            config = _profit_strategy_config(
                self._state.strategy_controls.mode,
                self._state.strategy_controls.horizon,
                self._state.strategy_controls.max_trades_per_year,
            )
            requires_market_regime = (
                config.apply_a_share_market_regime_filter
                or config.apply_a_share_relative_strength_filter
            ) and _is_a_share_security_id(security_id)

            async def load_market_regime() -> tuple[tuple[Bar, ...], tuple[str, ...]]:
                if not requires_market_regime:
                    return (), ()
                try:
                    values = await _run_provider_operation(
                        lambda: provider.get_bars(
                            BarsRequest(
                                security_id=config.market_regime_security_id,
                                interval=BarInterval.DAILY,
                                start_time=decision_start_time,
                                end_time=end_time,
                                adjustment=AdjustmentMode.FORWARD,
                            )
                        )
                    )
                except BaseException as error:  # noqa: BLE001
                    return (), (f"A股市场环境数据获取失败：{error}",)
                market_bars = tuple(values)
                if len(market_bars) <= config.market_regime_long_lookback:
                    return market_bars, (
                        "A股市场环境历史不足，当前禁止新开A股仓位："
                        f"{len(market_bars)}/{config.market_regime_long_lookback + 1} bars。",
                    )
                return market_bars, ()

            bars_result, decision_bars_result, quote, market_result = await asyncio.gather(
                _run_provider_operation(lambda: provider.get_bars(request)),
                _run_provider_operation(lambda: provider.get_bars(decision_request)),
                _run_provider_operation(lambda: provider.get_quote(security_id)),
                load_market_regime(),
            )
            bars = tuple(bars_result)
            decision_bars = tuple(decision_bars_result)
            market_regime_bars, market_issues = market_result
            issue_text = (() if bars else ("联网行情已连接，但历史K线为空。",)) + market_issues
            return _OnlineSecurityData(
                security_id=security_id,
                bars=bars,
                decision_bars=decision_bars or bars,
                market_regime_bars=market_regime_bars,
                quote=quote,
                data_health=DataHealth(
                    status=(
                        DataHealthStatus.HEALTHY
                        if bars and not market_issues
                        else DataHealthStatus.DEGRADED
                    ),
                    block_signal=requires_market_regime and bool(market_issues),
                    as_of=self._clock(),
                    issues=issue_text,
                ),
            )

        self._submit_background_job(
            kind="security_data",
            token=data_token,
            generation=generation,
            func=lambda: asyncio.run(load()),
        )

    def _submit_background_job(
        self,
        *,
        kind: _BackgroundJobKind,
        token: int,
        generation: int,
        func: Callable[[], object],
    ) -> None:
        future = self._executor.submit(func)
        self._background_jobs.append(
            _BackgroundJob(kind=kind, token=token, generation=generation, future=future)
        )
        if not self._background_poll_timer.isActive():
            self._background_poll_timer.start()

    @QtCore.Slot()
    def _drain_background_jobs(self) -> None:
        pending: list[_BackgroundJob] = []
        for job in self._background_jobs:
            if not job.future.done():
                pending.append(job)
                continue

            try:
                result = job.future.result()
            except BaseException as exc:  # noqa: BLE001 - converted to UI-safe health state.
                self._handle_background_failure(job, exc)
                continue

            if job.kind == "search":
                self._handle_online_search_result(job, result)
            elif job.kind == "security_data":
                self._handle_online_security_data(job, result)
            else:
                self._handle_online_market_overview(job, result)

        self._background_jobs = pending
        if not self._background_jobs:
            self._background_poll_timer.stop()

    def _handle_online_search_result(self, job: _BackgroundJob, result: object) -> None:
        if job.token != self._search_token:
            return
        if not isinstance(result, list):
            return

        query = self._state.search_query
        if not query:
            return

        securities = tuple(item for item in result if isinstance(item, SecurityRef))
        for security in securities:
            self._security_master.upsert_security(security)

        candidates = tuple(
            SearchCandidateState.from_search_result(
                SecuritySearchResult(
                    query=query or security.symbol,
                    security=security,
                    score=_online_search_score(query, security),
                    matched_fields=("online", "symbol"),
                )
            )
            for security in securities
        )
        self._set_state(
            self._state.model_copy(
                update={
                    "search_results": candidates,
                    "highlighted_search_index": 0 if candidates else None,
                    "run_state": UiRunState.SEARCHING if candidates else UiRunState.IDLE,
                    "latest_error": None,
                }
            )
        )

    def _handle_online_security_data(self, job: _BackgroundJob, result: object) -> None:
        if job.generation != self._state.selection_generation:
            return
        if job.token != self._security_data_token:
            return
        if not isinstance(result, _OnlineSecurityData):
            return
        if result.security_id != self._state.selected_security_id:
            return

        self._latest_decision_bars_by_security[result.security_id] = tuple(
            sorted(result.decision_bars, key=lambda item: item.end_time)
        )
        self.load_chart_bars(result.bars, generation=job.generation)
        self.apply_realtime_quote(result.quote, generation=job.generation)
        self.apply_data_health(result.data_health)
        self._apply_online_decision_report(result, generation=job.generation)
        self.apply_watchlist_market_snapshot(
            result.security_id,
            latest_price=result.quote.latest_price,
            change_pct=_quote_change_pct(result.quote),
            data_health=result.data_health,
        )
        self._set_state(
            self._state.model_copy(
                update={
                    "task_status": UiTaskStatus.COMPLETED,
                    "active_task_name": None,
                }
            )
        )

    def _handle_online_market_overview(self, job: _BackgroundJob, result: object) -> None:
        if job.token != self._market_overview_token:
            return
        if not isinstance(result, _OnlineMarketOverviewData):
            return
        if not result.overview.indices and result.failures:
            self._set_state(
                self._state.model_copy(
                    update={
                        "market_overview": MarketOverviewPanelState.failed(
                            _compact_failure_text(result.failures)
                        )
                    }
                )
            )
            return
        self.apply_market_overview(result.overview)

    def _apply_online_decision_report(
        self,
        result: _OnlineSecurityData,
        *,
        generation: int,
    ) -> None:
        try:
            selected_at = self._clock()
            security = self._security_master.select_security(
                result.security_id,
                selected_at=selected_at,
                as_of=selected_at.date(),
            )
            config = _profit_strategy_config(
                self._state.strategy_controls.mode,
                self._state.strategy_controls.horizon,
                self._state.strategy_controls.max_trades_per_year,
            )
            backtest = run_profit_strategy_backtest(
                result.security_id,
                result.decision_bars,
                config=config,
                include_walk_forward=True,
                market_regime_bars=result.market_regime_bars,
            )
            analysis = _analysis_report_from_profit_backtest(
                security=security,
                quote=result.quote,
                data_health=result.data_health,
                bars=result.decision_bars,
                backtest=backtest,
                mode=self._state.strategy_controls.mode,
            )
            request = DecisionRequest(
                security_id=result.security_id,
                as_of=analysis.as_of,
                evidence_window=f"{backtest.horizon.value}/{len(result.decision_bars)} bars",
                min_backtest_trades=max(1, min(3, config.max_trades_per_year)),
                max_backtest_drawdown=0.35,
                max_brier_score=0.35,
                require_simulation_evidence=True,
            )
            decision = DecisionHub().build_report(
                request=request,
                analysis_report=analysis,
                profitability=_profitability_evidence_from_backtest(backtest),
                simulation=None,
                out_of_sample_passed=backtest.status is ProfitValidationStatus.PASS,
                cost_stress_passed=backtest.cost_stress_passed,
            )
        except Exception:  # noqa: BLE001 - decision output is optional for market rendering.
            return
        self.apply_decision_report(decision, generation=generation)
        if not self._is_stale_generation(generation):
            self._set_state(
                self._state.model_copy(
                    update={
                        "backtest": BacktestPanelState.from_profit_result(backtest),
                        "task_status": UiTaskStatus.COMPLETED,
                        "active_task_name": None,
                    }
                )
            )

    def _handle_background_failure(self, job: _BackgroundJob, error: BaseException) -> None:
        if job.kind == "market_overview":
            if job.token == self._market_overview_token:
                self._set_state(
                    self._state.model_copy(
                        update={"market_overview": MarketOverviewPanelState.failed(str(error))}
                    )
                )
            return
        if job.kind == "search" and job.token != self._search_token:
            return
        if job.kind == "search" and (
            self._state.search_results or self._state.selected_security_id is not None
        ):
            return
        if job.kind == "security_data" and job.generation != self._state.selection_generation:
            return
        if job.kind == "security_data" and job.token != self._security_data_token:
            return

        prefix = "联网搜索失败" if job.kind == "search" else "联网行情失败"
        self.apply_data_health(
            DataHealth(
                status=DataHealthStatus.DEGRADED,
                block_signal=True,
                as_of=self._clock(),
                issues=_online_failure_issues(prefix, error),
            )
        )
        if job.kind == "security_data":
            self._set_state(
                self._state.model_copy(
                    update={
                        "task_status": UiTaskStatus.FAILED,
                        "active_task_name": None,
                    }
                )
            )

    def _complete_task(self, name: str, generation: int) -> None:
        if generation != self._state.selection_generation:
            return
        self._active_task = None
        self._set_state(
            self._state.model_copy(
                update={
                    "run_state": UiRunState.BACKTEST_COMPLETED,
                    "task_status": UiTaskStatus.COMPLETED,
                    "active_task_name": name,
                }
            )
        )

    def _mark_task_cancelled(self, name: str, generation: int) -> None:
        if generation != self._state.selection_generation:
            return
        self._active_task = None
        self._set_state(
            self._state.model_copy(
                update={
                    "run_state": UiRunState.IDLE,
                    "task_status": UiTaskStatus.CANCELLED,
                    "active_task_name": name,
                }
            )
        )

    def _fail_task(self, error: Any, generation: int) -> None:
        if generation != self._state.selection_generation:
            return
        self._active_task = None
        if isinstance(error, DomainError):
            self.apply_domain_error(error)
            self._set_state(
                self._state.model_copy(
                    update={
                        "task_status": UiTaskStatus.FAILED,
                        "active_task_name": None,
                    }
                )
            )
            return
        self._set_state(
            self._state.model_copy(
                update={
                    "run_state": UiRunState.BACKTEST_FAILED,
                    "task_status": UiTaskStatus.FAILED,
                    "active_task_name": None,
                }
            )
        )

    def _set_state(self, state: AppUiState) -> None:
        self._state = state
        self.state_changed.emit(state)

    def _is_stale_generation(self, generation: int | None) -> bool:
        return generation is not None and generation != self._state.selection_generation

    def _set_watchlist_items(self, items: tuple[WatchlistItemState, ...]) -> None:
        self._set_state(
            self._state.model_copy(update={"watchlist": _watchlist_panel_from_items(items)})
        )

    def _reload_selected_security_data(self) -> None:
        if self._market_data_provider is None:
            return
        security_id = self._state.selected_security_id
        if security_id is None:
            return
        self._start_online_security_data_load(security_id, self._state.selection_generation)

    def _cancel_background_security_data(self) -> None:
        if not any(job.kind == "security_data" for job in self._background_jobs):
            return
        self._security_data_token += 1
        for job in self._background_jobs:
            if job.kind == "security_data":
                job.future.cancel()
        self._background_jobs = [
            job for job in self._background_jobs if job.kind != "security_data"
        ]
        if not self._background_jobs:
            self._background_poll_timer.stop()
        next_run_state = (
            UiRunState.REALTIME_RUNNING if self._state.chart.points else UiRunState.IDLE
        )
        self._set_state(
            self._state.model_copy(
                update={
                    "run_state": next_run_state,
                    "task_status": UiTaskStatus.CANCELLED,
                    "active_task_name": "联网行情",
                }
            )
        )


async def _run_provider_operation[T](operation: Callable[[], Coroutine[Any, Any, T]]) -> T:
    return await asyncio.to_thread(lambda: asyncio.run(operation()))


async def _load_market_index_quote(
    *,
    provider: MarketDataProvider,
    security_id: str,
    as_of: datetime,
) -> Quote:
    try:
        return await provider.get_quote(security_id)
    except BaseException as quote_error:
        start_time = as_of - timedelta(days=21)
        try:
            bars = await provider.get_bars(
                BarsRequest(
                    security_id=security_id,
                    interval=BarInterval.DAILY,
                    start_time=start_time,
                    end_time=as_of,
                    adjustment=AdjustmentMode.NONE,
                )
            )
        except BaseException as bars_error:
            raise DataUnavailable(
                "指数quote失败，日K兜底也失败："
                f"quote={_short_error(quote_error)}；bars={_short_error(bars_error)}"
            ) from bars_error
        return _quote_from_latest_index_bars(security_id, tuple(bars), quote_error=quote_error)


def _quote_from_latest_index_bars(
    security_id: str,
    bars: tuple[Bar, ...],
    *,
    quote_error: BaseException,
) -> Quote:
    if not bars:
        raise DataUnavailable(f"指数quote失败且日K为空：{_short_error(quote_error)}")
    sorted_bars = tuple(sorted(bars, key=lambda bar: bar.end_time))
    latest = sorted_bars[-1]
    previous = sorted_bars[-2] if len(sorted_bars) >= 2 else latest
    return Quote(
        security_id=security_id,
        latest_price=latest.close_price,
        previous_close=previous.close_price,
        open_price=latest.open_price,
        high_price=latest.high_price,
        low_price=latest.low_price,
        volume=latest.volume,
        amount=latest.amount,
        provider=f"{latest.provider}.bar_fallback",
        schema_version="market_overview.bar_fallback.v1",
        source_time=latest.source_time,
        observed_at=latest.observed_at,
        received_at=latest.received_at,
        quality_status=latest.quality_status,
    )


def build_demo_security_master() -> SecurityMasterService:
    securities = (
        SecurityRef(
            security_id="SSE:600519",
            symbol="600519",
            name="贵州茅台",
            asset_type=AssetType.STOCK,
            exchange=Exchange.SSE,
            currency=Currency.CNY,
            listed_date=date(2001, 8, 27),
            status_date=date(2026, 6, 28),
            status=SecurityStatus.ACTIVE,
            aliases=("Kweichow Moutai", "茅台"),
        ),
        SecurityRef(
            security_id="SSE:510300",
            symbol="510300",
            name="沪深300ETF",
            asset_type=AssetType.ETF,
            exchange=Exchange.SSE,
            currency=Currency.CNY,
            listed_date=date(2012, 5, 28),
            status_date=date(2026, 6, 28),
            status=SecurityStatus.ACTIVE,
            aliases=("CSI300 ETF", "300ETF"),
        ),
        SecurityRef(
            security_id="FUND:000001",
            symbol="000001",
            name="华夏成长混合",
            asset_type=AssetType.MUTUAL_FUND,
            exchange=Exchange.FUND_COMPANY,
            currency=Currency.CNY,
            listed_date=date(2001, 12, 18),
            status_date=date(2026, 6, 28),
            status=SecurityStatus.ACTIVE,
            aliases=("Huaxia Growth",),
        ),
        SecurityRef(
            security_id="SSE:000001",
            symbol="000001",
            name="上证指数",
            asset_type=AssetType.INDEX,
            exchange=Exchange.SSE,
            currency=Currency.CNY,
            listed_date=date(1990, 12, 19),
            status_date=date(2026, 6, 28),
            status=SecurityStatus.ACTIVE,
            aliases=("SSE Composite", "上证综指", "INDEX:000001"),
        ),
        SecurityRef(
            security_id="SZSE:399001",
            symbol="399001",
            name="深证成指",
            asset_type=AssetType.INDEX,
            exchange=Exchange.SZSE,
            currency=Currency.CNY,
            listed_date=date(1991, 4, 3),
            status_date=date(2026, 6, 28),
            status=SecurityStatus.ACTIVE,
            aliases=("SZSE Component", "INDEX:399001"),
        ),
        SecurityRef(
            security_id="INDEX:000001",
            symbol="000001",
            name="上证指数",
            asset_type=AssetType.INDEX,
            exchange=Exchange.INDEX_PROVIDER,
            currency=Currency.CNY,
            listed_date=date(1990, 12, 19),
            status_date=date(2026, 6, 28),
            status=SecurityStatus.ACTIVE,
            aliases=("SSE Composite", "上证综指"),
        ),
        SecurityRef(
            security_id="INDEX:399001",
            symbol="399001",
            name="深证成指",
            asset_type=AssetType.INDEX,
            exchange=Exchange.INDEX_PROVIDER,
            currency=Currency.CNY,
            listed_date=date(1991, 4, 3),
            status_date=date(2026, 6, 28),
            status=SecurityStatus.ACTIVE,
            aliases=("SZSE Component",),
        ),
    )
    return SecurityMasterService.from_securities(securities)


def _run_state_for_analysis_report(report: AnalysisReport) -> UiRunState:
    if report.data_health.block_signal:
        return run_state_for_health(report.data_health)
    if report.abstain_reason is AbstainReason.INSUFFICIENT_HISTORY:
        return UiRunState.INSUFFICIENT_HISTORY
    if report.abstain_reason is AbstainReason.MODEL_UNCERTAINTY:
        return UiRunState.MODEL_OUT_OF_DISTRIBUTION
    return UiRunState.REALTIME_RUNNING


def _run_optimal_chart_backtest(
    *,
    security_id: str,
    bars: tuple[Bar, ...],
    fallback_points: tuple[ChartPointState, ...],
    horizon: HorizonPreset,
    max_trades: int,
) -> _OptimalChartBacktest | None:
    points = _chart_backtest_points(bars=bars, fallback_points=fallback_points, horizon=horizon)
    if len(points) < 2:
        return None
    trades = _maximize_profit_trades(points, max_trades=max_trades)
    total_return = _equity_total_return(points, trades)
    equity_curve = _chart_equity_curve(points, trades)
    max_drawdown = _max_drawdown_from_values(equity_curve)
    benchmark_return = points[-1].close_price / points[0].close_price - 1.0
    excess_return = total_return - benchmark_return
    wins = sum(1 for trade in trades if trade.net_return > 0)
    win_rate = 0.0 if not trades else wins / len(trades)
    days = max((_chart_point_date(points[-1]) - _chart_point_date(points[0])).days, 1)
    annualized_return = (1.0 + total_return) ** (365.0 / days) - 1.0
    signals = _chart_signals_from_optimal_trades(points, trades)
    trade_lines = _optimal_trade_lines(points, trades)
    summary = (
        f"图表利润最大化：净收益{_format_ui_percent(total_return)}，"
        f"最大回撤{_format_ui_percent(max_drawdown)}，"
        f"交易{len(trades)}/{max_trades}次。"
    )
    if not trades:
        summary = f"图表利润最大化：未找到正收益买卖路径，交易0/{max_trades}次。"
    panel = BacktestPanelState(
        status="OPTIMIZED",
        security_id=security_id,
        horizon_label=_horizon_ui_label(horizon),
        max_trades_per_year=str(max_trades),
        selected_threshold="MAX_PROFIT",
        total_return=_format_ui_percent(total_return),
        annualized_return=_format_ui_percent(annualized_return),
        max_drawdown=_format_ui_percent(max_drawdown),
        excess_return=_format_ui_percent(excess_return),
        win_rate=_format_ui_percent(win_rate),
        trade_count=str(len(trades)),
        brier_score="--",
        reliability_grade="H",
        summary=summary,
        trades=trade_lines,
        notes=(
            "本回测为当前可见图表窗口内的利润最大化历史路径，属于上帝视角。",
            "横轴、周期、复权和日期范围与当前图表一致，只叠加买卖标记。",
            "交易次数为当前图表窗口内最多完整买卖次数，可以少于上限但不能超过上限。",
            "该结果用于观察历史最佳路径，不代表未来可预测或可实现。",
        ),
    )
    return _OptimalChartBacktest(
        points=points,
        signals=signals,
        panel=panel,
    )


def _chart_backtest_points(
    *,
    bars: tuple[Bar, ...],
    fallback_points: tuple[ChartPointState, ...],
    horizon: HorizonPreset,
) -> tuple[ChartPointState, ...]:
    if len(fallback_points) >= 2:
        return fallback_points
    if bars:
        sorted_bars = tuple(sorted(bars, key=lambda item: item.end_time))
        end_time = sorted_bars[-1].end_time
        start_time = end_time - timedelta(days=_horizon_window_days(horizon))
        selected = tuple(bar for bar in sorted_bars if bar.end_time >= start_time)
        if len(selected) < 2:
            selected = sorted_bars[-min(len(sorted_bars), 2) :]
        return tuple(ChartPointState.from_bar(bar) for bar in selected)
    return fallback_points


def _maximize_profit_trades(
    points: tuple[ChartPointState, ...],
    *,
    max_trades: int,
) -> tuple[_OptimalChartTrade, ...]:
    max_completed_trades = max(0, min(max_trades, (len(points) - 1) // 2 + 1))
    if max_completed_trades <= 0:
        return ()
    prices = tuple(point.close_price for point in points)
    cash: list[tuple[float, tuple[tuple[str, int, float], ...]]] = [
        (1.0, ()),
        *[(-1.0, ()) for _ in range(max_completed_trades)],
    ]
    hold: list[tuple[float, tuple[tuple[str, int, float], ...]]] = [
        (-1.0, ()) for _ in range(max_completed_trades + 1)
    ]
    for index, price in enumerate(prices):
        if price <= 0:
            continue
        previous_cash = cash.copy()
        previous_hold = hold.copy()
        for trade_count in range(max_completed_trades + 1):
            cash_value, cash_path = previous_cash[trade_count]
            if cash_value <= 0:
                continue
            candidate_shares = cash_value / price
            if candidate_shares > hold[trade_count][0]:
                hold[trade_count] = (
                    candidate_shares,
                    (*cash_path, ("BUY", index, price)),
                )
        for trade_count in range(max_completed_trades):
            held_shares, hold_path = previous_hold[trade_count]
            if held_shares <= 0:
                continue
            candidate_cash = held_shares * price
            if candidate_cash > cash[trade_count + 1][0]:
                cash[trade_count + 1] = (
                    candidate_cash,
                    (*hold_path, ("SELL", index, price)),
                )
    best_cash, best_path = max(cash, key=lambda item: item[0])
    if best_cash <= 1.0 or not best_path:
        return ()
    return _events_to_optimal_trades(best_path)


def _events_to_optimal_trades(
    events: tuple[tuple[str, int, float], ...],
) -> tuple[_OptimalChartTrade, ...]:
    trades: list[_OptimalChartTrade] = []
    pending_buy: tuple[int, float] | None = None
    for action, index, price in events:
        if action == "BUY":
            pending_buy = (index, price)
            continue
        if action == "SELL" and pending_buy is not None and index > pending_buy[0]:
            entry_index, entry_price = pending_buy
            trades.append(
                _OptimalChartTrade(
                    entry_index=entry_index,
                    exit_index=index,
                    entry_price=entry_price,
                    exit_price=price,
                    net_return=price / entry_price - 1.0,
                )
            )
            pending_buy = None
    return tuple(trades)


def _chart_signals_from_optimal_trades(
    points: tuple[ChartPointState, ...],
    trades: tuple[_OptimalChartTrade, ...],
) -> tuple[ChartSignalMarkerState, ...]:
    markers: list[ChartSignalMarkerState] = []
    for trade in trades:
        entry = points[trade.entry_index]
        exit_point = points[trade.exit_index]
        entry_date = _chart_point_date(entry)
        exit_date = _chart_point_date(exit_point)
        markers.append(
            ChartSignalMarkerState(
                trade_date=entry_date,
                action=ChartSignalAction.BUY,
                price=trade.entry_price,
                label="B",
                detail=f"最大利润买入 {entry_date.isoformat()} @ {trade.entry_price:.3f}",
            )
        )
        markers.append(
            ChartSignalMarkerState(
                trade_date=exit_date,
                action=ChartSignalAction.SELL,
                price=trade.exit_price,
                label="S",
                detail=(
                    f"最大利润卖出 {exit_date.isoformat()} "
                    f"@ {trade.exit_price:.3f}；收益 {trade.net_return:.2%}"
                ),
            )
        )
    return tuple(markers)


def _optimal_trade_lines(
    points: tuple[ChartPointState, ...],
    trades: tuple[_OptimalChartTrade, ...],
) -> tuple[str, ...]:
    values: list[str] = []
    for index, trade in enumerate(trades, start=1):
        entry_date = _chart_point_date(points[trade.entry_index]).isoformat()
        exit_date = _chart_point_date(points[trade.exit_index]).isoformat()
        values.append(
            f"{index}. 买入 {entry_date} @ {trade.entry_price:.3f}；"
            f"卖出 {exit_date} @ {trade.exit_price:.3f}；"
            f"收益 {_format_ui_percent(trade.net_return)}；原因 max_profit"
        )
    return tuple(values)


def _chart_equity_curve(
    points: tuple[ChartPointState, ...],
    trades: tuple[_OptimalChartTrade, ...],
) -> tuple[float, ...]:
    cash = 1.0
    shares = 0.0
    trade_by_entry = {trade.entry_index: trade for trade in trades}
    trade_by_exit = {trade.exit_index: trade for trade in trades}
    values: list[float] = []
    for index, point in enumerate(points):
        if index in trade_by_entry and cash > 0:
            shares = cash / trade_by_entry[index].entry_price
            cash = 0.0
        value = cash if shares <= 0 else shares * point.close_price
        values.append(value)
        if index in trade_by_exit and shares > 0:
            cash = shares * trade_by_exit[index].exit_price
            shares = 0.0
            values[-1] = cash
    return tuple(values) or (1.0,)


def _equity_total_return(
    points: tuple[ChartPointState, ...],
    trades: tuple[_OptimalChartTrade, ...],
) -> float:
    equity = _chart_equity_curve(points, trades)
    return equity[-1] / equity[0] - 1.0


def _max_drawdown_from_values(values: tuple[float, ...]) -> float:
    peak = values[0] if values else 1.0
    drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1.0 if peak else 0.0)
    return drawdown


def _chart_point_date(point: ChartPointState) -> date:
    try:
        return datetime.fromisoformat(point.time_label).date()
    except ValueError:
        return date.min


def _horizon_window_days(horizon: HorizonPreset) -> int:
    match horizon:
        case HorizonPreset.ONE_MONTH:
            return 31
        case HorizonPreset.THREE_MONTHS:
            return 93
        case HorizonPreset.SIX_MONTHS:
            return 186
        case HorizonPreset.ONE_YEAR:
            return 366


def _chart_range_for_horizon(horizon: HorizonPreset) -> ChartRangePreset:
    match horizon:
        case HorizonPreset.ONE_MONTH:
            return ChartRangePreset.ONE_MONTH
        case HorizonPreset.THREE_MONTHS:
            return ChartRangePreset.THREE_MONTHS
        case HorizonPreset.SIX_MONTHS:
            return ChartRangePreset.SIX_MONTHS
        case HorizonPreset.ONE_YEAR:
            return ChartRangePreset.ONE_YEAR


def _horizon_ui_label(horizon: HorizonPreset) -> str:
    match horizon:
        case HorizonPreset.ONE_MONTH:
            return "1个月"
        case HorizonPreset.THREE_MONTHS:
            return "3个月"
        case HorizonPreset.SIX_MONTHS:
            return "6个月"
        case HorizonPreset.ONE_YEAR:
            return "1年"


def _format_ui_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _profit_strategy_config(
    mode: StrategyMode,
    horizon: HorizonPreset,
    max_trades_per_year: int,
) -> ProfitSeekingConfig:
    return profit_strategy_config(
        "long_term" if mode is StrategyMode.LONG_TERM else "short_term",
        horizon,
        max_trades_per_year,
    )


def _strategy_decision_start_time(end_time: datetime, horizon: HorizonPreset) -> datetime:
    parameters = horizon_parameters(horizon)
    bars_required = parameters.warmup_bars + 80 + max(80, parameters.holding_days)
    calendar_days = int(bars_required * 365 / 252) + 220
    return end_time - timedelta(days=max(370 * 6, calendar_days))


def _analysis_report_from_profit_backtest(
    *,
    security: SecurityRef,
    quote: Quote,
    data_health: DataHealth,
    bars: tuple[Bar, ...],
    backtest: ProfitBacktestResult,
    mode: StrategyMode,
) -> AnalysisReport:
    parameters = horizon_parameters(backtest.horizon)
    forecast = forecast_interval_from_bars(
        bars,
        horizon_days=parameters.holding_days,
        round_trip_cost_bps=15.0,
    )
    final_signal = _profit_analysis_signal(backtest, data_health, forecast, mode)
    strategy_id = (
        "strategy.profit_validation_long_term"
        if mode is StrategyMode.LONG_TERM
        else "strategy.profit_validation_short_term"
    )
    strategy_version = (
        "profit-validation-long-v3"
        if mode is StrategyMode.LONG_TERM
        else "profit-validation-short-v7"
    )
    return AnalysisReport(
        security_id=security.security_id,
        as_of=quote.source_time,
        data_health=data_health,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        horizon=parameters.holding_days,
        market_regime=_profit_market_regime(backtest, forecast),
        direction_probabilities=_profit_direction_probabilities(backtest, forecast),
        raw_signal=_profit_raw_signal(backtest, forecast, mode),
        final_signal=final_signal,
        valid_until=quote.source_time + timedelta(days=1),
        positive_drivers=_profit_positive_drivers(security, backtest, forecast, mode),
        negative_drivers=_profit_negative_drivers(backtest, data_health, forecast),
        model_version=forecast.model_version,
        rule_version="rules-profit-validation-short-asset-gate-v1"
        if mode is StrategyMode.SHORT_TERM
        else "rules-profit-validation-long-v3",
        data_snapshot_id=f"profit-validation:{len(bars)}-daily-bars",
        expected_return_quantiles=_profit_expected_return_quantiles(backtest, forecast),
        expected_drawdown=forecast.expected_drawdown,
        grade=_effective_reliability_grade(backtest, forecast),
        target_position_limit=_target_position_limit(final_signal, backtest, forecast, mode),
        exit_or_invalidation_conditions=_profit_invalidation_conditions(backtest, mode),
        abstain_reason=(
            _profit_abstain_reason(backtest, data_health, forecast)
            if final_signal is FinalSignal.ABSTAIN
            else None
        ),
    )


def _profitability_evidence_from_backtest(
    backtest: ProfitBacktestResult,
) -> ProfitabilityEvidence:
    return ProfitabilityEvidence(
        source="profit_validation_oos",
        strategy_id=_strategy_id_for_horizon(backtest.horizon),
        strategy_version=_strategy_version_for_horizon(backtest.horizon),
        total_return=backtest.total_return,
        annualized_return=backtest.annualized_return,
        annualized_volatility=backtest.annualized_volatility,
        sharpe_ratio=backtest.sharpe_ratio,
        calmar_ratio=backtest.calmar_ratio,
        max_drawdown=backtest.max_drawdown,
        benchmark_total_return=backtest.benchmark_total_return,
        benchmark_max_drawdown=backtest.benchmark_max_drawdown,
        excess_return=backtest.excess_return,
        trade_count=backtest.trade_count,
        turnover=backtest.turnover,
        cost_drag=backtest.cost_drag,
        average_position_fraction=backtest.average_position_fraction,
        stress_round_trip_cost_bps=backtest.stress_round_trip_cost_bps,
        stress_total_return=backtest.stress_total_return,
        stress_max_drawdown=backtest.stress_max_drawdown,
        cost_stress_passed=backtest.cost_stress_passed,
        calibration_sample_count=backtest.calibration_sample_count,
        brier_score=backtest.brier_score,
        walk_forward_positive_ratio=backtest.walk_forward_positive_ratio,
        walk_forward_participation_ratio=backtest.walk_forward_participation_ratio,
        walk_forward_excess_ratio=backtest.walk_forward_excess_ratio,
        walk_forward_median_return=backtest.walk_forward_median_return,
        checksum=backtest.checksum,
        notes=backtest.notes,
    )


def _strategy_id_for_horizon(horizon: HorizonPreset) -> str:
    if horizon in {HorizonPreset.SIX_MONTHS, HorizonPreset.ONE_YEAR}:
        return "strategy.profit_validation_long_term"
    return "strategy.profit_validation_short_term"


def _strategy_version_for_horizon(horizon: HorizonPreset) -> str:
    if horizon in {HorizonPreset.SIX_MONTHS, HorizonPreset.ONE_YEAR}:
        return "profit-validation-long-v3"
    return "profit-validation-short-v7"


def _profit_analysis_signal(
    backtest: ProfitBacktestResult,
    data_health: DataHealth,
    forecast: IntervalForecastResult,
    mode: StrategyMode,
) -> FinalSignal:
    if data_health.block_signal or backtest.status is ProfitValidationStatus.INSUFFICIENT_HISTORY:
        return FinalSignal.ABSTAIN
    if backtest.status is ProfitValidationStatus.FAIL and backtest.excess_return <= 0:
        return FinalSignal.ABSTAIN
    probabilities = forecast.direction_probabilities
    p50 = forecast.expected_return_quantiles.get("p50", 0.0)
    p05 = forecast.expected_return_quantiles.get("p05", -1.0)
    pass_like = backtest.status is ProfitValidationStatus.PASS
    enough_forecast = forecast.similar_sample_count >= 25 and forecast.confidence >= 0.28
    calibrated_forecast = _forecast_validation_passes(forecast)
    if probabilities.down >= 0.58 and p50 <= 0:
        return FinalSignal.SELL
    if probabilities.down >= 0.48 and p50 <= 0:
        return FinalSignal.REDUCE
    if backtest.market_regime.status in {
        MarketRegimeGateStatus.BLOCKED,
        MarketRegimeGateStatus.MISSING,
    }:
        return FinalSignal.ABSTAIN
    if backtest.relative_strength.status in {
        MarketRegimeGateStatus.BLOCKED,
        MarketRegimeGateStatus.MISSING,
    }:
        return FinalSignal.ABSTAIN
    if _is_a_share_stock_id(backtest.security_id) and not pass_like:
        return FinalSignal.ABSTAIN
    if (
        pass_like
        and backtest.cost_stress_passed is True
        and enough_forecast
        and calibrated_forecast
        and probabilities.up >= 0.48
        and p50 > 0
    ):
        return FinalSignal.BUY_CANDIDATE
    if pass_like and p50 > 0 and p05 > -0.12:
        return FinalSignal.HOLD if mode is StrategyMode.LONG_TERM else FinalSignal.WATCH
    if (
        backtest.total_return > 0
        and backtest.cost_stress_passed is True
        and (backtest.walk_forward_positive_ratio or 0.0) >= 0.55
        and probabilities.up > probabilities.down
    ):
        return FinalSignal.HOLD
    return FinalSignal.WATCH


def _profit_abstain_reason(
    backtest: ProfitBacktestResult,
    data_health: DataHealth,
    forecast: IntervalForecastResult,
) -> AbstainReason | None:
    if data_health.block_signal:
        return AbstainReason.DATA
    if backtest.status is ProfitValidationStatus.INSUFFICIENT_HISTORY:
        return AbstainReason.INSUFFICIENT_HISTORY
    if backtest.market_regime.status is MarketRegimeGateStatus.MISSING:
        return AbstainReason.DATA
    if backtest.market_regime.status is MarketRegimeGateStatus.BLOCKED:
        return AbstainReason.RULE
    if backtest.relative_strength.status is MarketRegimeGateStatus.MISSING:
        return AbstainReason.DATA
    if backtest.relative_strength.status is MarketRegimeGateStatus.BLOCKED:
        return AbstainReason.RULE
    if forecast.similar_sample_count <= 0:
        return AbstainReason.MODEL_UNCERTAINTY
    if (
        _is_a_share_stock_id(backtest.security_id)
        and backtest.status is not ProfitValidationStatus.PASS
    ):
        return AbstainReason.EXPECTED_VALUE
    if backtest.status is ProfitValidationStatus.FAIL and backtest.excess_return <= 0:
        return AbstainReason.EXPECTED_VALUE
    return None


def _profit_raw_signal(
    backtest: ProfitBacktestResult,
    forecast: IntervalForecastResult,
    mode: StrategyMode,
) -> str:
    probabilities = forecast.direction_probabilities
    mode_prefix = "SHORT_TERM" if mode is StrategyMode.SHORT_TERM else "LONG_TERM"
    if backtest.market_regime.status is MarketRegimeGateStatus.MISSING:
        return "ABSTAIN_A_SHARE_MARKET_REGIME_MISSING"
    if backtest.market_regime.status is MarketRegimeGateStatus.BLOCKED:
        return "ABSTAIN_A_SHARE_MARKET_REGIME_BLOCKED"
    if backtest.relative_strength.status is MarketRegimeGateStatus.MISSING:
        return "ABSTAIN_A_SHARE_RELATIVE_STRENGTH_MISSING"
    if backtest.relative_strength.status is MarketRegimeGateStatus.BLOCKED:
        return "ABSTAIN_A_SHARE_RELATIVE_STRENGTH_BLOCKED"
    if probabilities.down >= 0.50:
        return f"{mode_prefix}_SELL_OR_REDUCE_BIAS"
    if (
        _is_a_share_stock_id(backtest.security_id)
        and backtest.status is not ProfitValidationStatus.PASS
    ):
        return "ABSTAIN_A_SHARE_STOCK_EVIDENCE_NOT_PASSED"
    if probabilities.up >= 0.50 and backtest.status is ProfitValidationStatus.PASS:
        return f"{mode_prefix}_BUY_CANDIDATE_BIAS"
    if backtest.status is ProfitValidationStatus.PASS:
        return f"{mode_prefix}_HOLD_OR_WATCH_AFTER_PROFIT_VALIDATION"
    if backtest.status is ProfitValidationStatus.WATCH:
        return f"{mode_prefix}_WATCH_NEEDS_MORE_EVIDENCE"
    if backtest.status is ProfitValidationStatus.INSUFFICIENT_HISTORY:
        return "ABSTAIN_INSUFFICIENT_HISTORY"
    return "ABSTAIN_PROFIT_VALIDATION_FAILED"


def _profit_market_regime(
    backtest: ProfitBacktestResult,
    forecast: IntervalForecastResult,
) -> str:
    regime = backtest.market_regime
    if regime.status is MarketRegimeGateStatus.PASS:
        return f"A_SHARE_MARKET_GATE_PASS_{regime.short_lookback}D_{regime.long_lookback}D"
    if regime.status is MarketRegimeGateStatus.BLOCKED:
        return f"A_SHARE_MARKET_GATE_BLOCKED_{regime.short_lookback}D_{regime.long_lookback}D"
    if regime.status is MarketRegimeGateStatus.MISSING:
        return "A_SHARE_MARKET_GATE_MISSING"
    probabilities = forecast.direction_probabilities
    if probabilities.down >= 0.55:
        return "RISK_OFF_DOWNSIDE_DOMINANT"
    if probabilities.up >= 0.55:
        return "RISK_ON_UPSIDE_DOMINANT"
    if backtest.status is ProfitValidationStatus.PASS:
        return "PROFIT_VALIDATED_RESEARCH"
    if backtest.status is ProfitValidationStatus.WATCH:
        return "WATCHLIST_RESEARCH"
    if backtest.status is ProfitValidationStatus.INSUFFICIENT_HISTORY:
        return "INSUFFICIENT_HISTORY"
    return "NEGATIVE_EXPECTED_VALUE"


def _profit_direction_probabilities(
    backtest: ProfitBacktestResult,
    forecast: IntervalForecastResult,
) -> DirectionProbabilities:
    if forecast.similar_sample_count > 0:
        return forecast.direction_probabilities
    if backtest.status is ProfitValidationStatus.PASS:
        return DirectionProbabilities(up=0.56, flat=0.29, down=0.15)
    if backtest.status is ProfitValidationStatus.WATCH and backtest.total_return > 0:
        return DirectionProbabilities(up=0.44, flat=0.39, down=0.17)
    if backtest.status is ProfitValidationStatus.FAIL:
        return DirectionProbabilities(up=0.20, flat=0.35, down=0.45)
    return DirectionProbabilities(up=0.25, flat=0.50, down=0.25)


def _profit_expected_return_quantiles(
    backtest: ProfitBacktestResult,
    forecast: IntervalForecastResult,
) -> dict[str, float]:
    if forecast.expected_return_quantiles:
        return forecast.expected_return_quantiles
    return {}


def _profit_positive_drivers(
    security: SecurityRef,
    backtest: ProfitBacktestResult,
    forecast: IntervalForecastResult,
    mode: StrategyMode,
) -> tuple[str, ...]:
    values: list[str] = []
    values.append(
        "短线模式：偏重5-21日动量、量能确认和回撤控制。"
        if mode is StrategyMode.SHORT_TERM
        else "长线模式：偏重63-252日趋势、相对强弱和波动稳定性。"
    )
    if mode is StrategyMode.SHORT_TERM and _is_a_share_security(security):
        values.append("A股个股启用反追涨约束：单日涨幅不超过3%，21日动量不超过15%。")
        values.append(
            "回测按收盘信号次日开盘执行，止损不使用未知日内先后顺序，"
            "并应用A股T+1、停牌和一字涨跌停成交阻断。"
        )
        if backtest.market_regime.status is MarketRegimeGateStatus.PASS:
            values.append(
                "沪深300市场门槛通过："
                f"{backtest.market_regime.short_lookback}日动量"
                f"{(backtest.market_regime.short_momentum or 0.0):.1%}，"
                f"{backtest.market_regime.long_lookback}日动量"
                f"{(backtest.market_regime.long_momentum or 0.0):.1%}。"
            )
        if backtest.relative_strength.status is MarketRegimeGateStatus.PASS:
            values.append(
                "相对沪深300强弱门槛通过："
                f"短期{(backtest.relative_strength.short_relative_momentum or 0.0):.1%}，"
                f"中期{(backtest.relative_strength.long_relative_momentum or 0.0):.1%}。"
            )
    values.extend(forecast.notes[:2])
    if backtest.total_return > 0:
        values.append(f"样本外扣费净收益 {backtest.total_return:.2%}。")
    if backtest.excess_return > 0:
        values.append(f"相对买入持有超额 {backtest.excess_return:.2%}。")
    if backtest.trade_count > 0:
        values.append(f"样本外成交 {backtest.trade_count} 次，胜率 {backtest.win_rate:.1%}。")
    if backtest.average_position_fraction is not None:
        values.append(
            f"20%目标波动下历史平均策略暴露 {backtest.average_position_fraction:.0%}，"
            "高波动阶段只减仓、不加杠杆。"
        )
    if backtest.sharpe_ratio is not None:
        values.append(
            f"样本外Sharpe {backtest.sharpe_ratio:.2f}，Calmar {backtest.calmar_ratio:.2f}。"
            if backtest.calmar_ratio is not None
            else f"样本外Sharpe {backtest.sharpe_ratio:.2f}。"
        )
    if backtest.walk_forward_positive_ratio is not None:
        values.append(
            f"滚动前推有效{backtest.walk_forward_active_folds}折，"
            f"正收益折占比 {backtest.walk_forward_positive_ratio:.0%}，"
            f"折中位收益 {(backtest.walk_forward_median_return or 0.0):.2%}。"
        )
    if backtest.cost_stress_passed is True and backtest.stress_total_return is not None:
        values.append(
            f"提高到{backtest.stress_round_trip_cost_bps or 0:.0f}bp往返成本后，"
            f"样本外收益仍为 {backtest.stress_total_return:.2%}。"
        )
    if backtest.status is ProfitValidationStatus.PASS:
        values.append("盈利、回撤、基准比较三项暂时通过。")
    return tuple(values) or ("暂无足够正向赚钱证据。",)


def _target_position_limit(
    final_signal: FinalSignal,
    backtest: ProfitBacktestResult,
    forecast: IntervalForecastResult,
    mode: StrategyMode,
) -> float:
    if final_signal is FinalSignal.BUY_CANDIDATE:
        base = 0.08 if mode is StrategyMode.SHORT_TERM else 0.12
    elif final_signal is FinalSignal.HOLD:
        base = 0.05 if mode is StrategyMode.SHORT_TERM else 0.10
    else:
        return 0.0
    if backtest.reliability_grade.value == "A":
        multiplier = 1.0
    elif backtest.reliability_grade.value == "B":
        multiplier = 0.70
    else:
        multiplier = 0.35
    if forecast.confidence < 0.40:
        multiplier *= 0.60
    if not _forecast_validation_passes(forecast):
        multiplier *= 0.50
    if (
        backtest.walk_forward_positive_ratio is not None
        and backtest.walk_forward_positive_ratio < 0.60
    ):
        multiplier *= 0.60
    if abs(backtest.max_drawdown) > 0.25:
        multiplier *= 0.50
    if backtest.average_position_fraction is not None:
        multiplier *= min(1.0, backtest.average_position_fraction)
    return round(base * multiplier, 4)


def _profit_negative_drivers(
    backtest: ProfitBacktestResult,
    data_health: DataHealth,
    forecast: IntervalForecastResult,
) -> tuple[str, ...]:
    values: list[str] = []
    if (
        _is_a_share_stock_id(backtest.security_id)
        and backtest.status is not ProfitValidationStatus.PASS
    ):
        values.append(
            "当前A股个股的单标的样本外与滚动前推证据未通过；"
            "允许卖出或减仓风控提示，但不支持新增仓位。"
        )
    if backtest.market_regime.status is MarketRegimeGateStatus.BLOCKED:
        values.append(
            "沪深300的21日与63日动量未同时为正，市场门槛阻断A股新开仓；"
            f"样本内已拒绝{backtest.market_regime.rejected_entry_count}次候选。"
        )
    elif backtest.market_regime.status is MarketRegimeGateStatus.MISSING:
        values.append("沪深300市场代理数据不足，无法验证大盘环境，禁止新开A股仓位。")
    if backtest.relative_strength.status is MarketRegimeGateStatus.BLOCKED:
        values.append(
            "个股相对沪深300强弱未通过实验门槛，禁止新开仓；"
            f"样本内已拒绝{backtest.relative_strength.rejected_entry_count}次候选。"
        )
    elif backtest.relative_strength.status is MarketRegimeGateStatus.MISSING:
        values.append("个股或沪深300样本不足，无法验证相对强弱，禁止新开仓。")
    if forecast.confidence < 0.45:
        values.append(f"预测置信度偏低：{forecast.confidence:.0%}，需要更多相似样本验证。")
    if len(forecast.notes) >= 3:
        values.append(forecast.notes[2])
    if forecast.validation is None:
        values.append("预测区间缺少滚动校准证据，暂不宜作为单独操作依据。")
    elif forecast.validation.interval_coverage is not None:
        if forecast.validation.interval_coverage < 0.70:
            values.append(f"预测区间历史覆盖率偏低：{forecast.validation.interval_coverage:.0%}。")
        if (
            forecast.validation.direction_brier_score is not None
            and forecast.validation.direction_brier_score > 0.30
        ):
            values.append(
                f"方向概率历史Brier偏高：{forecast.validation.direction_brier_score:.3f}。"
            )
    if backtest.status is ProfitValidationStatus.INSUFFICIENT_HISTORY:
        values.extend(backtest.notes)
    values.extend(
        [
            f"最大回撤 {backtest.max_drawdown:.2%}。",
            f"策略状态 {backtest.status.value}。",
        ]
    )
    if backtest.status is not ProfitValidationStatus.INSUFFICIENT_HISTORY:
        values.extend(backtest.notes)
    if backtest.excess_return <= 0:
        values.append(f"相对基准超额未为正：{backtest.excess_return:.2%}。")
    if backtest.average_position_fraction is not None and backtest.average_position_fraction < 0.75:
        values.append(
            f"历史平均暴露仅 {backtest.average_position_fraction:.0%}："
            "标的波动较高，账户建议已同步降低仓位上限。"
        )
    if backtest.walk_forward_positive_ratio is None:
        values.append("缺少滚动前推一致性指标，最终留出收益不能单独证明稳定性。")
    elif backtest.walk_forward_positive_ratio < 0.55:
        values.append(
            f"滚动前推正收益折仅 {backtest.walk_forward_positive_ratio:.0%}，跨窗口稳定性不足。"
        )
    if backtest.cost_stress_passed is not True:
        if backtest.stress_total_return is None:
            values.append("缺少固定交易路径的提高成本压力测试。")
        else:
            values.append(
                f"提高成本后样本外收益 {backtest.stress_total_return:.2%}，成本压力未通过。"
            )
    if backtest.trade_count <= 0:
        values.append("样本外没有形成足够交易，不能证明可赚钱。")
    if backtest.brier_score is None:
        values.append("概率校准样本缺失，无法证明预测概率可靠。")
    if data_health.block_signal:
        values.extend(f"数据健康阻断：{issue}" for issue in data_health.issues)
    return tuple(dict.fromkeys(values))


def _forecast_validation_passes(forecast: IntervalForecastResult) -> bool:
    validation = forecast.validation
    if validation is None:
        return False
    return (
        validation.sample_count >= 40
        and validation.interval_coverage is not None
        and validation.interval_coverage >= 0.68
        and validation.downside_breach_rate is not None
        and validation.downside_breach_rate <= 0.22
        and validation.direction_brier_score is not None
        and validation.direction_brier_score <= 0.30
    )


def _effective_reliability_grade(
    backtest: ProfitBacktestResult,
    forecast: IntervalForecastResult,
) -> str:
    grade = backtest.reliability_grade.value
    if grade in {"A", "B"} and (
        not _forecast_validation_passes(forecast)
        or backtest.cost_stress_passed is not True
        or (backtest.walk_forward_positive_ratio or 0.0) < 0.55
    ):
        return "C"
    return grade


def _profit_invalidation_conditions(
    backtest: ProfitBacktestResult,
    mode: StrategyMode,
) -> tuple[str, ...]:
    values = [
        "模拟盘成交与偏差证据未通过前，不允许进入真实API下单候选。",
        "若后续回测扣费净收益转负或相对基准超额转负，策略失效。",
        "若固定交易路径在提高成本后转为亏损，取消买入候选并重新验证。",
        "短线若跌破止损或量价背离需要退出。"
        if mode is StrategyMode.SHORT_TERM
        else "长线若中长期趋势跌破或最大回撤扩大需要降仓。",
    ]
    if backtest.status is ProfitValidationStatus.INSUFFICIENT_HISTORY:
        values.append("补足长期日线历史后重新验证。")
    return tuple(values)


def _is_a_share_security(security: SecurityRef) -> bool:
    return security.asset_type is AssetType.STOCK and _is_a_share_stock_id(security.security_id)


def _is_a_share_stock_id(security_id: str) -> bool:
    exchange, _separator, symbol = security_id.partition(":")
    if exchange == Exchange.SSE.value:
        return symbol.startswith(("600", "601", "603", "605", "688", "689"))
    if exchange == Exchange.SZSE.value:
        return symbol.startswith(("000", "001", "002", "003", "300", "301"))
    return False


def _is_a_share_security_id(security_id: str) -> bool:
    exchange, _separator, symbol = security_id.partition(":")
    if exchange == Exchange.SSE.value:
        return symbol.startswith(("600", "601", "603", "605", "688", "689"))
    if exchange == Exchange.SZSE.value:
        return symbol.startswith(("000", "001", "002", "003", "300", "301"))
    return False


def _watchlist_panel_from_items(items: tuple[WatchlistItemState, ...]) -> WatchlistPanelState:
    groups: dict[str, list[WatchlistItemState]] = {}
    for item in items:
        groups.setdefault(item.group, []).append(item)
    group_states = tuple(
        WatchlistGroupState(
            name=group_name,
            items=tuple(
                sorted(
                    group_items,
                    key=lambda item: (not item.pinned, item.sort_order, item.symbol),
                )
            ),
        )
        for group_name, group_items in sorted(groups.items())
    )
    return WatchlistPanelState(groups=group_states)


def _next_sort_order(items: tuple[WatchlistItemState, ...], group: str) -> int:
    group_orders = tuple(item.sort_order for item in items if item.group == group)
    if not group_orders:
        return 0
    return max(group_orders) + 1


def _watchlist_item_with_signal(
    item: WatchlistItemState,
    *,
    final_signal: FinalSignal,
    latest_price: float | None,
    change_pct: float | None,
    data_health: DataHealth | None,
) -> WatchlistItemState:
    updates: dict[str, object] = {"final_signal": final_signal.value}
    if latest_price is not None:
        updates["latest_price"] = f"{latest_price:.2f}"
    if change_pct is not None:
        updates["change_pct"] = f"{change_pct * 100:.1f}%"
    if data_health is not None:
        issue_text = "；".join(data_health.issues)
        updates["data_health_text"] = (
            f"{data_health.status.value}: {issue_text}" if issue_text else data_health.status.value
        )
        updates["is_stale"] = data_health.status is DataHealthStatus.STALE
    return item.model_copy(update=updates)


def _watchlist_item_with_market_snapshot(
    item: WatchlistItemState,
    *,
    latest_price: float | None,
    change_pct: float | None,
    data_health: DataHealth | None,
) -> WatchlistItemState:
    updates: dict[str, object] = {}
    if latest_price is not None:
        updates["latest_price"] = f"{latest_price:.2f}"
    if change_pct is not None:
        updates["change_pct"] = f"{change_pct * 100:.1f}%"
    if data_health is not None:
        issue_text = "；".join(data_health.issues)
        updates["data_health_text"] = (
            f"{data_health.status.value}: {issue_text}" if issue_text else data_health.status.value
        )
        updates["is_stale"] = data_health.status is DataHealthStatus.STALE
    return item.model_copy(update=updates)


def _quote_change_pct(quote: Quote) -> float | None:
    if quote.previous_close <= 0:
        return None
    return (quote.latest_price - quote.previous_close) / quote.previous_close


def _looks_like_security_code_or_symbol(query: str) -> bool:
    normalized = query.strip().upper()
    if normalized.isdigit() and len(normalized) == 6:
        return True
    if _hk_code_from_query(normalized) is not None:
        return True
    if _looks_like_us_symbol(normalized):
        return True
    if "." in normalized:
        market, _, code = normalized.partition(".")
        return market in {"0", "1"} and code.isdigit() and len(code) == 6
    if ":" in normalized:
        exchange, _, code = normalized.partition(":")
        if exchange in {"SSE", "SH", "SZSE", "SZ"} and code.isdigit() and len(code) == 6:
            return True
        if exchange in _HK_EXCHANGE_ALIASES and _canonical_hk_code(code) is not None:
            return True
        return exchange in {"NASDAQ", "NYSE", "US"} and _looks_like_us_symbol(code)
    return False


def _fallback_security_from_query(query: str, *, as_of: date) -> SecurityRef | None:
    normalized = query.strip().upper()
    exchange: Exchange
    symbol: str
    hk_code = _hk_code_from_query(normalized)
    if normalized.isdigit() and len(normalized) == 6:
        symbol = normalized
        exchange = Exchange.SSE if symbol[0] in {"5", "6", "9"} else Exchange.SZSE
    elif hk_code is not None:
        return _fallback_hk_security(symbol=hk_code, as_of=as_of)
    elif "." in normalized:
        market, _, code = normalized.partition(".")
        if market not in {"0", "1"} or not (code.isdigit() and len(code) == 6):
            return None
        symbol = code
        exchange = Exchange.SSE if market == "1" else Exchange.SZSE
    elif ":" in normalized:
        exchange_text, _, code = normalized.partition(":")
        if code.isdigit() and len(code) == 6:
            if exchange_text in {"SSE", "SH"}:
                exchange = Exchange.SSE
            elif exchange_text in {"SZSE", "SZ"}:
                exchange = Exchange.SZSE
            else:
                return None
            symbol = code
        elif _looks_like_us_symbol(code):
            if exchange_text in {"NASDAQ", "US"}:
                return _fallback_us_security(
                    symbol=code,
                    exchange=Exchange.NASDAQ,
                    as_of=as_of,
                )
            if exchange_text == "NYSE":
                return _fallback_us_security(symbol=code, exchange=Exchange.NYSE, as_of=as_of)
            return None
        else:
            return None
    elif _looks_like_us_symbol(normalized):
        symbol = normalized
        exchange = Exchange.NASDAQ
        return _fallback_us_security(symbol=symbol, exchange=exchange, as_of=as_of)
    else:
        return None
    return SecurityRef(
        security_id=f"{exchange.value}:{symbol}",
        symbol=symbol,
        name=f"{symbol}（代码兜底）",
        asset_type=_fallback_asset_type(symbol),
        exchange=exchange,
        currency=Currency.CNY,
        listed_date=date(1990, 1, 1),
        status_date=as_of,
        status=SecurityStatus.ACTIVE,
        aliases=("code-fallback",),
    )


def _fallback_us_security(*, symbol: str, exchange: Exchange, as_of: date) -> SecurityRef:
    return SecurityRef(
        security_id=f"{exchange.value}:{symbol}",
        symbol=symbol,
        name=f"{symbol}（美股代码兜底）",
        asset_type=_fallback_us_asset_type(symbol),
        exchange=exchange,
        currency=Currency.USD,
        listed_date=date(1990, 1, 1),
        status_date=as_of,
        status=SecurityStatus.ACTIVE,
        aliases=("us-code-fallback", "yahoo-symbol"),
    )


_HK_EXCHANGE_ALIASES = frozenset({"HK", "HKEX", "HKG", "SEHK"})


def _fallback_hk_security(*, symbol: str, as_of: date) -> SecurityRef:
    return SecurityRef(
        security_id=f"{Exchange.HKEX.value}:{symbol}",
        symbol=symbol,
        name=f"{symbol}（港股代码兜底）",
        asset_type=AssetType.STOCK,
        exchange=Exchange.HKEX,
        currency=Currency.HKD,
        listed_date=date(1990, 1, 1),
        status_date=as_of,
        status=SecurityStatus.ACTIVE,
        aliases=("hk-code-fallback", "yahoo-hk-symbol", _hk_yahoo_symbol(symbol)),
    )


def _hk_code_from_query(value: str) -> str | None:
    normalized = value.strip().upper()
    code: str | None = None
    if ":" in normalized:
        exchange, _, raw_code = normalized.partition(":")
        if exchange in _HK_EXCHANGE_ALIASES:
            code = raw_code
    elif normalized.endswith(".HK"):
        code = normalized.removesuffix(".HK")
    elif normalized.isdigit() and 4 <= len(normalized) <= 5:
        code = normalized
    if code is None:
        return None
    return _canonical_hk_code(code)


def _canonical_hk_code(code: str) -> str | None:
    normalized = code.strip().upper()
    if not normalized.isdigit() or not (1 <= len(normalized) <= 5):
        return None
    return (normalized.lstrip("0") or "0").zfill(5)


def _hk_yahoo_symbol(code: str) -> str:
    canonical = _canonical_hk_code(code) or code
    stripped = canonical.lstrip("0") or "0"
    yahoo_code = stripped.zfill(4) if len(stripped) <= 4 else stripped
    return f"{yahoo_code}.HK"


def _fallback_asset_type(symbol: str) -> AssetType:
    if symbol.startswith(("5", "15", "16", "18")):
        return AssetType.ETF
    if symbol.startswith(("0", "3", "6", "8", "9")):
        return AssetType.STOCK
    return AssetType.STOCK


def _fallback_us_asset_type(symbol: str) -> AssetType:
    if symbol in {"DIA", "IWM", "QQQ", "SPY", "VOO", "VTI"}:
        return AssetType.ETF
    return AssetType.STOCK


def _looks_like_us_symbol(value: str) -> bool:
    symbol = value.strip().upper()
    if not (1 <= len(symbol) <= 8):
        return False
    return all(character.isalpha() or character in {".", "-"} for character in symbol)


def _range_start(end_time: datetime, range_preset: ChartRangePreset) -> datetime:
    match range_preset:
        case ChartRangePreset.FIVE_DAYS:
            days = 10
        case ChartRangePreset.THREE_MONTHS:
            days = 110
        case ChartRangePreset.SIX_MONTHS:
            days = 210
        case ChartRangePreset.ONE_YEAR:
            days = 370
        case ChartRangePreset.THREE_YEARS:
            days = 370 * 3
        case ChartRangePreset.FIVE_YEARS:
            days = 370 * 5
        case ChartRangePreset.CUSTOM:
            days = 370
        case _:
            days = 45
    return end_time - timedelta(days=days)


def _online_search_score(query: str, security: SecurityRef) -> float:
    normalized = query.strip().upper()
    if normalized in {security.symbol.upper(), security.security_id.upper()}:
        return 1.0
    return 0.9 if normalized and normalized in security.symbol.upper() else 0.8


def _short_error(error: BaseException) -> str:
    if isinstance(error, DomainError):
        return error.engineering_message
    message = str(error).strip()
    return message or error.__class__.__name__


def _online_failure_issues(prefix: str, error: BaseException) -> tuple[str, ...]:
    return (
        f"{prefix}：{_short_error(error)}",
        "A股收盘后实时价可能停在收盘价，但历史K线仍应可获取；失败通常不是因为15:00后闭市。",
        "请检查打包程序是否能访问东方财富公共接口，以及系统代理、防火墙或证书设置。",
    )


def _compact_failure_text(failures: tuple[str, ...]) -> str:
    text = "；".join(failures)
    if len(text) <= 96:
        return text
    return f"{text[:93]}..."


__all__ = ["ApplicationViewModel", "CancellableQtTask", "build_demo_security_master"]
