"""Qt ViewModel and cancellable task shell."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
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
    DomainError,
    Exchange,
    FinalSignal,
    Quote,
    SecurityRef,
    SecurityStatus,
)
from china_quant_platform.knowledge import KnowledgeCenter
from china_quant_platform.market import MarketOverview
from china_quant_platform.ui.state import (
    AnalysisPanelState,
    AppUiState,
    ChartOverlay,
    ChartPointState,
    ChartRangePreset,
    KnowledgeCenterState,
    SearchCandidateState,
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


_BackgroundJobKind = Literal["search", "security_data"]


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
    quote: Quote
    data_health: DataHealth


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
        self._state = AppUiState(
            knowledge=KnowledgeCenterState.from_topics(self._knowledge_center.list_topics())
        )

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
            not candidates or _looks_like_security_code(stripped_query)
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

    def select_security(self, security_id: str) -> None:
        if self._active_task is not None:
            self.cancel_active_task()

        selected_at = self._clock()
        security = self._security_master.select_security(
            security_id,
            selected_at=selected_at,
            as_of=selected_at.date(),
        )
        next_generation = self._state.selection_generation + 1
        self._set_state(
            self._state.model_copy(
                update={
                    "selection_generation": next_generation,
                    "selected_security_id": security.security_id,
                    "search_query": "",
                    "search_results": (),
                    "highlighted_search_index": None,
                    "chart": self._state.chart.model_copy(
                        update={
                            "points": (),
                            "update_count": self._state.chart.update_count + 1,
                            "realtime_update_count": 0,
                        }
                    ),
                    "analysis": AnalysisPanelState(),
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
        self._set_state(
            self._state.model_copy(
                update={"chart": self._state.chart.model_copy(update={"interval": interval})}
            )
        )

    def set_chart_adjustment(self, adjustment: AdjustmentMode) -> None:
        self._set_state(
            self._state.model_copy(
                update={"chart": self._state.chart.model_copy(update={"adjustment": adjustment})}
            )
        )

    def set_chart_range(self, range_preset: ChartRangePreset) -> None:
        self._set_state(
            self._state.model_copy(
                update={
                    "chart": self._state.chart.model_copy(update={"range_preset": range_preset})
                }
            )
        )

    def set_chart_overlay_enabled(self, overlay: ChartOverlay, enabled: bool) -> None:
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
            bars = tuple(await provider.get_bars(request))
            quote = await provider.get_quote(security_id)
            issue_text = () if bars else ("联网行情已连接，但历史K线为空。",)
            return _OnlineSecurityData(
                security_id=security_id,
                bars=bars,
                quote=quote,
                data_health=DataHealth(
                    status=DataHealthStatus.HEALTHY if bars else DataHealthStatus.DEGRADED,
                    block_signal=False,
                    as_of=self._clock(),
                    issues=issue_text,
                ),
            )

        self._submit_background_job(
            kind="security_data",
            token=generation,
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
            else:
                self._handle_online_security_data(job, result)

        self._background_jobs = pending
        if not self._background_jobs:
            self._background_poll_timer.stop()

    def _handle_online_search_result(self, job: _BackgroundJob, result: object) -> None:
        if job.token != self._search_token:
            return
        if not isinstance(result, list):
            return

        securities = tuple(item for item in result if isinstance(item, SecurityRef))
        for security in securities:
            self._security_master.upsert_security(security)

        query = self._state.search_query
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
        if not isinstance(result, _OnlineSecurityData):
            return
        if result.security_id != self._state.selected_security_id:
            return

        self.load_chart_bars(result.bars, generation=job.generation)
        self.apply_realtime_quote(result.quote, generation=job.generation)
        self.apply_data_health(result.data_health)
        self._set_state(
            self._state.model_copy(
                update={
                    "task_status": UiTaskStatus.COMPLETED,
                    "active_task_name": None,
                }
            )
        )

    def _handle_background_failure(self, job: _BackgroundJob, error: BaseException) -> None:
        if job.kind == "search" and job.token != self._search_token:
            return
        if job.kind == "security_data" and job.generation != self._state.selection_generation:
            return

        prefix = "联网搜索失败" if job.kind == "search" else "联网行情失败"
        self.apply_data_health(
            DataHealth(
                status=DataHealthStatus.DEGRADED,
                block_signal=True,
                as_of=self._clock(),
                issues=(f"{prefix}：{_short_error(error)}",),
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


def _looks_like_security_code(query: str) -> bool:
    normalized = query.strip().upper()
    if normalized.isdigit() and len(normalized) == 6:
        return True
    if "." in normalized:
        market, _, code = normalized.partition(".")
        return market in {"0", "1"} and code.isdigit() and len(code) == 6
    if ":" in normalized:
        exchange, _, code = normalized.partition(":")
        return exchange in {"SSE", "SH", "SZSE", "SZ"} and code.isdigit() and len(code) == 6
    return False


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


__all__ = ["ApplicationViewModel", "CancellableQtTask", "build_demo_security_master"]
