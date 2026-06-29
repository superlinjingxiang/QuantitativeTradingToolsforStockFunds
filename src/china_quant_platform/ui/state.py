"""GUI state models for the PySide6 shell."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from china_quant_platform.data import SecuritySearchResult
from china_quant_platform.domain import (
    AdjustmentMode,
    AnalysisReport,
    Bar,
    BarInterval,
    DataHealth,
    DataHealthStatus,
    DomainErrorKind,
    FinalSignal,
    Quote,
)
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.market import IndexSnapshot, MarketOverview


class UiRunState(StrEnum):
    IDLE = "IDLE"
    SEARCHING = "SEARCHING"
    LOADING_CACHE_HISTORY = "LOADING_CACHE_HISTORY"
    FETCHING_REMOTE_HISTORY = "FETCHING_REMOTE_HISTORY"
    CONNECTING_REALTIME = "CONNECTING_REALTIME"
    REALTIME_RUNNING = "REALTIME_RUNNING"
    COMPUTING_STRATEGY = "COMPUTING_STRATEGY"
    DATA_STALE = "DATA_STALE"
    DATA_QUALITY_BLOCKED = "DATA_QUALITY_BLOCKED"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    MODEL_OUT_OF_DISTRIBUTION = "MODEL_OUT_OF_DISTRIBUTION"
    BACKTEST_RUNNING = "BACKTEST_RUNNING"
    BACKTEST_CANCELLING = "BACKTEST_CANCELLING"
    BACKTEST_FAILED = "BACKTEST_FAILED"
    BACKTEST_COMPLETED = "BACKTEST_COMPLETED"
    ERROR = "ERROR"


class UiTaskStatus(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class ChartRangePreset(StrEnum):
    FIVE_DAYS = "5d"
    ONE_MONTH = "1m"
    THREE_MONTHS = "3m"
    SIX_MONTHS = "6m"
    ONE_YEAR = "1y"
    THREE_YEARS = "3y"
    FIVE_YEARS = "5y"
    CUSTOM = "custom"


class ChartOverlay(StrEnum):
    MOVING_AVERAGE = "MA"
    EXPONENTIAL_AVERAGE = "EMA"
    VOLUME = "VOLUME"
    SIGNALS = "SIGNALS"
    FORECAST = "FORECAST"


class ChartPointState(DomainModel):
    time_label: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    amount: float
    is_realtime: bool = False

    @classmethod
    def from_bar(cls, bar: Bar) -> ChartPointState:
        return cls(
            time_label=bar.end_time.isoformat(),
            open_price=bar.open_price,
            high_price=bar.high_price,
            low_price=bar.low_price,
            close_price=bar.close_price,
            volume=bar.volume,
            amount=bar.amount,
        )

    @classmethod
    def from_quote(cls, quote: Quote) -> ChartPointState:
        return cls(
            time_label=quote.source_time.isoformat(),
            open_price=quote.open_price,
            high_price=quote.high_price,
            low_price=quote.low_price,
            close_price=quote.latest_price,
            volume=quote.volume,
            amount=quote.amount,
            is_realtime=True,
        )


class ChartState(DomainModel):
    interval: BarInterval = BarInterval.DAILY
    adjustment: AdjustmentMode = AdjustmentMode.NONE
    range_preset: ChartRangePreset = ChartRangePreset.ONE_MONTH
    overlays: frozenset[ChartOverlay] = frozenset({ChartOverlay.VOLUME})
    points: tuple[ChartPointState, ...] = ()
    update_count: int = 0
    realtime_update_count: int = 0

    @property
    def point_count(self) -> int:
        return len(self.points)


class UiErrorState(DomainModel):
    kind: DomainErrorKind
    user_message: str
    engineering_message: str
    retryable: bool
    blocks_signal: bool


class SearchCandidateState(DomainModel):
    security_id: str
    symbol: str
    name: str
    asset_type: str
    exchange: str
    status: str
    score: float
    matched_fields: tuple[str, ...]

    @classmethod
    def from_search_result(cls, result: SecuritySearchResult) -> SearchCandidateState:
        security = result.security
        return cls(
            security_id=security.security_id,
            symbol=security.symbol,
            name=security.name,
            asset_type=security.asset_type.value,
            exchange=security.exchange.value,
            status=security.status.value,
            score=result.score,
            matched_fields=result.matched_fields,
        )


class StrategyPanelState(DomainModel):
    strategy_name: str = "--"
    strategy_id: str = "--"
    strategy_version: str = "--"
    horizon_label: str = "--"
    market_regime: str = "--"
    raw_signal: str = "--"
    applicable_conditions: tuple[str, ...] = ()
    invalidation_conditions: tuple[str, ...] = ()
    model_version: str = "--"
    rule_version: str = "--"
    data_snapshot_id: str = "--"


class ForecastPanelState(DomainModel):
    direction_label: str = "--"
    probability_summary: str = "--"
    expected_return_range: str = "--"
    expected_drawdown: str = "--"
    confidence_note: str = "--"
    model_version: str = "--"
    is_abstain: bool = False


class OperationPanelState(DomainModel):
    final_signal: str = "--"
    grade: str = "--"
    valid_until: str = "--"
    target_position_limit: str = "--"
    positive_drivers: tuple[str, ...] = ()
    negative_drivers: tuple[str, ...] = ()
    exit_or_invalidation_conditions: tuple[str, ...] = ()
    abstain_reason: str | None = None


class AnalysisPanelState(DomainModel):
    report: AnalysisReport | None = None
    strategy: StrategyPanelState = Field(default_factory=StrategyPanelState)
    forecast: ForecastPanelState = Field(default_factory=ForecastPanelState)
    operation: OperationPanelState = Field(default_factory=OperationPanelState)

    @classmethod
    def from_report(
        cls,
        report: AnalysisReport,
        *,
        strategy_name: str | None = None,
        strategy_summary: str | None = None,
        applicable_conditions: tuple[str, ...] = (),
    ) -> AnalysisPanelState:
        invalidation_conditions = tuple(report.exit_or_invalidation_conditions)
        strategy = StrategyPanelState(
            strategy_name=strategy_name or report.strategy_id,
            strategy_id=report.strategy_id,
            strategy_version=report.strategy_version,
            horizon_label=f"{report.horizon} bars",
            market_regime=report.market_regime,
            raw_signal=report.raw_signal,
            applicable_conditions=applicable_conditions or _fallback_applicable_conditions(report),
            invalidation_conditions=invalidation_conditions,
            model_version=report.model_version,
            rule_version=report.rule_version,
            data_snapshot_id=report.data_snapshot_id,
        )
        forecast = ForecastPanelState(
            direction_label=_direction_label(report),
            probability_summary=_probability_summary(report),
            expected_return_range=_return_range(report),
            expected_drawdown=_drawdown_text(report.expected_drawdown),
            confidence_note=_confidence_note(strategy_summary),
            model_version=report.model_version,
            is_abstain=report.final_signal is FinalSignal.ABSTAIN,
        )
        operation = OperationPanelState(
            final_signal=report.final_signal.value,
            grade=report.grade or "--",
            valid_until=report.valid_until.isoformat(),
            target_position_limit=_position_limit_text(report.target_position_limit),
            positive_drivers=tuple(report.positive_drivers),
            negative_drivers=_negative_driver_text(report),
            exit_or_invalidation_conditions=invalidation_conditions,
            abstain_reason=(
                report.abstain_reason.value if report.abstain_reason is not None else None
            ),
        )
        return cls(report=report, strategy=strategy, forecast=forecast, operation=operation)


class MarketIndexPanelState(DomainModel):
    security_id: str
    name: str
    latest_value: str
    change_pct: str
    turnover: str
    source_time: str

    @classmethod
    def from_snapshot(cls, snapshot: IndexSnapshot) -> MarketIndexPanelState:
        return cls(
            security_id=snapshot.security_id,
            name=snapshot.name,
            latest_value=f"{snapshot.latest_value:.2f}",
            change_pct=_format_percent(snapshot.change_pct),
            turnover=_money_text(snapshot.turnover),
            source_time=snapshot.source_time.isoformat(),
        )


class MarketOverviewPanelState(DomainModel):
    as_of: str = "--"
    indices: tuple[MarketIndexPanelState, ...] = ()
    breadth_summary: str = "--"
    turnover_summary: str = "--"
    volatility_state: str = "--"
    trend_state: str = "--"
    data_health_text: str = "--"
    is_stale: bool = False

    @classmethod
    def from_overview(cls, overview: MarketOverview) -> MarketOverviewPanelState:
        breadth = overview.breadth
        return cls(
            as_of=overview.as_of.isoformat(),
            indices=tuple(MarketIndexPanelState.from_snapshot(index) for index in overview.indices),
            breadth_summary=(
                f"上涨{breadth.advancers} / 下跌{breadth.decliners} / 平盘{breadth.unchanged}"
            ),
            turnover_summary=_money_text(breadth.total_turnover),
            volatility_state=breadth.volatility_state.value,
            trend_state=breadth.trend_state.value,
            data_health_text=_data_health_text(overview.data_health),
            is_stale=overview.data_health.status is DataHealthStatus.STALE,
        )


class WatchlistItemState(DomainModel):
    security_id: str
    symbol: str
    name: str
    group: str
    sort_order: int = 0
    pinned: bool = False
    final_signal: str = "--"
    latest_price: str = "--"
    change_pct: str = "--"
    data_health_text: str = "--"
    is_stale: bool = False


class WatchlistGroupState(DomainModel):
    name: str
    items: tuple[WatchlistItemState, ...] = ()


class WatchlistPanelState(DomainModel):
    groups: tuple[WatchlistGroupState, ...] = ()

    @property
    def items(self) -> tuple[WatchlistItemState, ...]:
        return tuple(item for group in self.groups for item in group.items)


class AppUiState(DomainModel):
    selection_generation: int = 0
    selected_security_id: str | None = None
    search_query: str = ""
    search_results: tuple[SearchCandidateState, ...] = ()
    highlighted_search_index: int | None = None
    run_state: UiRunState = UiRunState.IDLE
    task_status: UiTaskStatus = UiTaskStatus.IDLE
    active_task_name: str | None = None
    data_health: DataHealth | None = None
    market_overview: MarketOverviewPanelState = Field(default_factory=MarketOverviewPanelState)
    watchlist: WatchlistPanelState = Field(default_factory=WatchlistPanelState)
    chart: ChartState = Field(default_factory=ChartState)
    analysis: AnalysisPanelState = Field(default_factory=AnalysisPanelState)
    latest_error: UiErrorState | None = None

    @property
    def is_signal_blocked(self) -> bool:
        return self.data_health.block_signal if self.data_health is not None else False

    @property
    def banner_text(self) -> str:
        if self.data_health is None:
            return "数据健康：未连接"
        issue_text = "；".join(self.data_health.issues)
        if issue_text:
            return f"数据健康：{self.data_health.status.value}｜{issue_text}"
        return f"数据健康：{self.data_health.status.value}"


def run_state_for_health(data_health: DataHealth) -> UiRunState:
    if not data_health.block_signal:
        return UiRunState.REALTIME_RUNNING
    if data_health.status is DataHealthStatus.STALE:
        return UiRunState.DATA_STALE
    return UiRunState.DATA_QUALITY_BLOCKED


def run_state_for_error(kind: DomainErrorKind) -> UiRunState:
    match kind:
        case DomainErrorKind.DATA_STALE:
            return UiRunState.DATA_STALE
        case DomainErrorKind.DATA_INVALID | DomainErrorKind.UNAUTHORIZED_DATA:
            return UiRunState.DATA_QUALITY_BLOCKED
        case DomainErrorKind.INSUFFICIENT_HISTORY:
            return UiRunState.INSUFFICIENT_HISTORY
        case DomainErrorKind.MODEL_OUT_OF_DISTRIBUTION:
            return UiRunState.MODEL_OUT_OF_DISTRIBUTION
        case _:
            return UiRunState.ERROR


def _direction_label(report: AnalysisReport) -> str:
    probabilities = report.direction_probabilities
    if report.final_signal is FinalSignal.ABSTAIN:
        return "不明确/不交易"
    if probabilities.up >= 0.65:
        return "强势上涨"
    if probabilities.up >= 0.50:
        return "震荡上涨"
    if probabilities.down >= 0.65:
        return "强势下跌"
    if probabilities.down >= 0.50:
        return "震荡下跌"
    if probabilities.flat >= 0.45:
        return "横盘"
    return "不明确/不交易"


def _probability_summary(report: AnalysisReport) -> str:
    probabilities = report.direction_probabilities
    return (
        f"上涨{_format_percent(probabilities.up)} / "
        f"横盘{_format_percent(probabilities.flat)} / "
        f"下跌{_format_percent(probabilities.down)}"
    )


def _return_range(report: AnalysisReport) -> str:
    p05 = report.expected_return_quantiles.get("p05")
    p50 = report.expected_return_quantiles.get("p50")
    p95 = report.expected_return_quantiles.get("p95")
    if p05 is None or p95 is None:
        return "--"
    if p50 is None:
        return f"{_format_percent(p05)} to {_format_percent(p95)}"
    return f"{_format_percent(p05)} to {_format_percent(p95)}; p50 {_format_percent(p50)}"


def _drawdown_text(drawdown: float | None) -> str:
    if drawdown is None:
        return "--"
    return _format_percent(drawdown)


def _confidence_note(strategy_summary: str | None) -> str:
    warning = "预测区间，不代表确定未来价格。"
    if not strategy_summary:
        return warning
    return f"{strategy_summary} {warning}"


def _negative_driver_text(report: AnalysisReport) -> tuple[str, ...]:
    values = list(report.negative_drivers)
    if report.data_health.block_signal:
        issues = "；".join(report.data_health.issues) or "data gate blocks new signals"
        health_text = f"Data health {report.data_health.status.value}: {issues}"
        if health_text not in values:
            values.append(health_text)
    return tuple(values)


def _position_limit_text(limit: float | None) -> str:
    if limit is None:
        return "--"
    return _format_percent(limit)


def _format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _money_text(value: float) -> str:
    if value >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if value >= 10_000:
        return f"{value / 10_000:.2f}万"
    return f"{value:.2f}"


def _data_health_text(data_health: DataHealth) -> str:
    issue_text = "；".join(data_health.issues)
    if issue_text:
        return f"{data_health.status.value}: {issue_text}"
    return data_health.status.value


def _fallback_applicable_conditions(report: AnalysisReport) -> tuple[str, ...]:
    if report.final_signal is FinalSignal.ABSTAIN:
        return ("No new trade while the report is abstaining.",)
    return ("Data, rule, and risk gates are required before execution.",)


__all__ = [
    "AnalysisPanelState",
    "AppUiState",
    "ChartOverlay",
    "ChartPointState",
    "ChartRangePreset",
    "ChartState",
    "ForecastPanelState",
    "MarketIndexPanelState",
    "MarketOverviewPanelState",
    "OperationPanelState",
    "SearchCandidateState",
    "StrategyPanelState",
    "UiErrorState",
    "UiRunState",
    "UiTaskStatus",
    "WatchlistGroupState",
    "WatchlistItemState",
    "WatchlistPanelState",
    "run_state_for_error",
    "run_state_for_health",
]
