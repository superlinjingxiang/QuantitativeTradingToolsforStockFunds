"""GUI state models for the PySide6 shell."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field

from china_quant_platform.data import SecuritySearchResult
from china_quant_platform.decision import DecisionReport, EvidenceGateStatus
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
    SecurityRef,
)
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.knowledge import HelpTopic
from china_quant_platform.market import IndexSnapshot, MarketOverview
from china_quant_platform.strategies.profit_validation import (
    HorizonPreset,
    ProfitBacktestResult,
    ProfitValidationStatus,
)


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


class ChartSignalAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class StrategyMode(StrEnum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"


class StrategyControlState(DomainModel):
    mode: StrategyMode = StrategyMode.SHORT_TERM
    horizon: HorizonPreset = HorizonPreset.ONE_MONTH
    max_trades_per_year: int = Field(default=12, ge=1, le=60)
    algorithm_name: str = "短线盈利验证"

    @classmethod
    def for_mode(cls, mode: StrategyMode) -> StrategyControlState:
        if mode is StrategyMode.LONG_TERM:
            return cls(
                mode=mode,
                horizon=HorizonPreset.SIX_MONTHS,
                max_trades_per_year=4,
                algorithm_name="长线趋势验证",
            )
        return cls(
            mode=mode,
            horizon=HorizonPreset.ONE_MONTH,
            max_trades_per_year=12,
            algorithm_name="短线盈利验证",
        )

    @property
    def horizon_label(self) -> str:
        return _horizon_label(self.horizon)

    @property
    def mode_label(self) -> str:
        return _strategy_mode_label(self.mode)

    @property
    def mode_description(self) -> str:
        return _strategy_mode_description(self.mode)


class BacktestPanelState(DomainModel):
    status: str = "--"
    security_id: str = "--"
    horizon_label: str = "--"
    max_trades_per_year: str = "--"
    selected_threshold: str = "--"
    total_return: str = "--"
    annualized_return: str = "--"
    annualized_volatility: str = "--"
    sharpe_ratio: str = "--"
    calmar_ratio: str = "--"
    max_drawdown: str = "--"
    benchmark_max_drawdown: str = "--"
    excess_return: str = "--"
    win_rate: str = "--"
    trade_count: str = "--"
    brier_score: str = "--"
    reliability_grade: str = "--"
    walk_forward_consistency: str = "--"
    summary: str = "暂无回测结果"
    notes: tuple[str, ...] = ()
    trades: tuple[str, ...] = ()

    @classmethod
    def from_profit_result(cls, result: ProfitBacktestResult) -> BacktestPanelState:
        return cls(
            status=result.status.value,
            security_id=result.security_id,
            horizon_label=_horizon_label(result.horizon),
            max_trades_per_year=str(result.max_trades_per_year),
            selected_threshold=f"{result.selected_threshold:.2f}",
            total_return=_format_percent(result.total_return),
            annualized_return=_format_percent(result.annualized_return),
            annualized_volatility=_format_percent(result.annualized_volatility),
            sharpe_ratio=("--" if result.sharpe_ratio is None else f"{result.sharpe_ratio:.2f}"),
            calmar_ratio=("--" if result.calmar_ratio is None else f"{result.calmar_ratio:.2f}"),
            max_drawdown=_format_percent(result.max_drawdown),
            benchmark_max_drawdown=_format_percent(result.benchmark_max_drawdown),
            excess_return=_format_percent(result.excess_return),
            win_rate=_format_percent(result.win_rate),
            trade_count=str(result.trade_count),
            brier_score="--" if result.brier_score is None else f"{result.brier_score:.4f}",
            reliability_grade=result.reliability_grade.value,
            walk_forward_consistency=(
                "--"
                if result.walk_forward_positive_ratio is None
                else (
                    f"正收益折{_format_percent(result.walk_forward_positive_ratio)}；"
                    f"折中位{_format_percent(result.walk_forward_median_return or 0.0)}；"
                    f"有效{result.walk_forward_active_folds}折"
                )
            ),
            summary=_backtest_summary(result),
            notes=tuple(result.notes),
            trades=_profit_trade_summaries(result),
        )


class ChartPointState(DomainModel):
    time_label: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    amount: float
    reference_price: float | None = None
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
            reference_price=quote.previous_close,
            is_realtime=True,
        )


class ChartSignalMarkerState(DomainModel):
    trade_date: date
    action: ChartSignalAction
    price: float
    label: str
    detail: str


class ChartState(DomainModel):
    interval: BarInterval = BarInterval.DAILY
    adjustment: AdjustmentMode = AdjustmentMode.NONE
    range_preset: ChartRangePreset = ChartRangePreset.ONE_MONTH
    overlays: frozenset[ChartOverlay] = frozenset({ChartOverlay.VOLUME})
    points: tuple[ChartPointState, ...] = ()
    signals: tuple[ChartSignalMarkerState, ...] = ()
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


class RecentSecurityState(DomainModel):
    security_id: str
    symbol: str
    name: str
    asset_type: str
    exchange: str

    @classmethod
    def from_security_ref(cls, security: SecurityRef) -> RecentSecurityState:
        return cls(
            security_id=security.security_id,
            symbol=security.symbol,
            name=security.name,
            asset_type=security.asset_type.value,
            exchange=security.exchange.value,
        )


class StrategyPanelState(DomainModel):
    strategy_name: str = "--"
    strategy_id: str = "--"
    strategy_version: str = "--"
    mode_label: str = "--"
    asset_scope: str = "--"
    horizon_label: str = "--"
    market_regime: str = "--"
    raw_signal: str = "--"
    core_indicators: tuple[str, ...] = ()
    sample_count: str = "--"
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
    validation_metrics: str = "--"
    confidence_note: str = "--"
    model_version: str = "--"
    is_abstain: bool = False


class OperationPanelState(DomainModel):
    final_signal: str = "--"
    grade: str = "--"
    grade_description: str = "--"
    valid_until: str = "--"
    target_position_limit: str = "--"
    positive_drivers: tuple[str, ...] = ()
    negative_drivers: tuple[str, ...] = ()
    exit_or_invalidation_conditions: tuple[str, ...] = ()
    abstain_reason: str | None = None


class DecisionPanelState(DomainModel):
    report: DecisionReport | None = None
    final_signal: str = "--"
    readiness: str = "--"
    confidence: str = "--"
    target_position_limit: str = "--"
    profitability_summary: str = "--"
    simulation_summary: str = "--"
    gate_summary: str = "--"
    gate_details: tuple[str, ...] = ()
    blocking_reasons: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()
    no_profit_guarantee: str = "--"

    @classmethod
    def from_report(cls, report: DecisionReport) -> DecisionPanelState:
        return cls(
            report=report,
            final_signal=report.final_signal.value,
            readiness=report.execution_readiness.value,
            confidence=_format_percent(report.confidence),
            target_position_limit=_position_limit_text(report.target_position_limit),
            profitability_summary=_profitability_summary(report),
            simulation_summary=_simulation_summary(report),
            gate_summary=_gate_summary(report),
            gate_details=_gate_details(report),
            blocking_reasons=tuple(report.negative_evidence),
            caveats=tuple(report.caveats),
            no_profit_guarantee=report.no_profit_guarantee,
        )


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
            mode_label=_mode_label_from_strategy(report),
            asset_scope=_asset_scope_from_strategy(report),
            horizon_label=f"{report.horizon} bars",
            market_regime=report.market_regime,
            raw_signal=report.raw_signal,
            core_indicators=_core_indicators_from_strategy(report),
            sample_count=_sample_count_from_report(report),
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
            validation_metrics=_validation_metrics_from_report(report),
            confidence_note=_confidence_note(strategy_summary),
            model_version=report.model_version,
            is_abstain=report.final_signal is FinalSignal.ABSTAIN,
        )
        operation = OperationPanelState(
            final_signal=report.final_signal.value,
            grade=report.grade or "--",
            grade_description=_grade_description(report.grade),
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
    def placeholder(
        cls, *, security_id: str, name: str, status: str = "等待行情"
    ) -> MarketIndexPanelState:
        return cls(
            security_id=security_id,
            name=name,
            latest_value="--",
            change_pct=status,
            turnover="--",
            source_time="--",
        )

    @classmethod
    def from_snapshot(cls, snapshot: IndexSnapshot) -> MarketIndexPanelState:
        return cls(
            security_id=snapshot.security_id,
            name=snapshot.name,
            latest_value=f"{snapshot.latest_value:.2f}",
            change_pct=_format_signed_percent(snapshot.change_pct),
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
    def placeholder(cls, *, status: str = "等待行情") -> MarketOverviewPanelState:
        return cls(
            indices=_default_market_index_states(status=status),
            breadth_summary=status,
            turnover_summary="--",
            volatility_state="--",
            trend_state="--",
            data_health_text=status,
        )

    @classmethod
    def loading(cls) -> MarketOverviewPanelState:
        return cls.placeholder(status="刷新中")

    @classmethod
    def failed(cls, message: str) -> MarketOverviewPanelState:
        return cls(
            indices=_default_market_index_states(status="获取失败"),
            breadth_summary="--",
            turnover_summary="--",
            volatility_state="--",
            trend_state="--",
            data_health_text=f"获取失败：{message}",
        )

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


class KnowledgeTopicState(DomainModel):
    topic_id: str
    title: str
    summary: str

    @classmethod
    def from_topic(cls, topic: HelpTopic) -> KnowledgeTopicState:
        return cls(topic_id=topic.topic_id, title=topic.title, summary=topic.summary)


class KnowledgeCenterState(DomainModel):
    query: str = ""
    topics: tuple[KnowledgeTopicState, ...] = ()
    selected_topic_id: str | None = None
    selected_title: str = "--"
    selected_body: str = "--"

    @classmethod
    def from_topics(
        cls,
        topics: tuple[HelpTopic, ...],
        *,
        query: str = "",
        selected: HelpTopic | None = None,
    ) -> KnowledgeCenterState:
        selected_topic = selected or (topics[0] if topics else None)
        return cls(
            query=query,
            topics=tuple(KnowledgeTopicState.from_topic(topic) for topic in topics),
            selected_topic_id=None if selected_topic is None else selected_topic.topic_id,
            selected_title="--" if selected_topic is None else selected_topic.title,
            selected_body="--" if selected_topic is None else _knowledge_body(selected_topic),
        )


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
    strategy_controls: StrategyControlState = Field(default_factory=StrategyControlState)
    market_overview: MarketOverviewPanelState = Field(
        default_factory=MarketOverviewPanelState.placeholder
    )
    watchlist: WatchlistPanelState = Field(default_factory=WatchlistPanelState)
    recent_securities: tuple[RecentSecurityState, ...] = ()
    knowledge: KnowledgeCenterState = Field(default_factory=KnowledgeCenterState)
    chart: ChartState = Field(default_factory=ChartState)
    analysis: AnalysisPanelState = Field(default_factory=AnalysisPanelState)
    decision: DecisionPanelState = Field(default_factory=DecisionPanelState)
    backtest: BacktestPanelState = Field(default_factory=BacktestPanelState)
    chart_backtest_active: bool = False
    latest_error: UiErrorState | None = None

    @property
    def is_signal_blocked(self) -> bool:
        return self.data_health.block_signal if self.data_health is not None else False

    @property
    def banner_text(self) -> str:
        if self.data_health is None:
            return "数据健康：等待行情"
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


def _profitability_summary(report: DecisionReport) -> str:
    evidence = report.profitability
    if evidence is None:
        return "历史赚钱证据：缺失"
    total_return = "--" if evidence.total_return is None else _format_percent(evidence.total_return)
    max_drawdown = "--" if evidence.max_drawdown is None else _format_percent(evidence.max_drawdown)
    excess_return = (
        "--" if evidence.excess_return is None else _format_percent(evidence.excess_return)
    )
    return (
        f"历史净收益：{total_return}；最大回撤：{max_drawdown}；"
        f"相对基准：{excess_return}；交易次数：{evidence.trade_count}"
    )


def _simulation_summary(report: DecisionReport) -> str:
    evidence = report.simulation
    if evidence is None:
        return "模拟盘证据：缺失"
    slippage = (
        "--"
        if evidence.max_abs_slippage_pct is None
        else _format_percent(evidence.max_abs_slippage_pct)
    )
    return (
        f"模拟净值：{evidence.net_asset_value:.2f}；成交：{evidence.execution_count}；"
        f"偏差超限：{evidence.threshold_breach_count}；最大滑点：{slippage}"
    )


def _gate_summary(report: DecisionReport) -> str:
    blocked = tuple(
        gate
        for gate in report.gates
        if gate.status in {EvidenceGateStatus.FAIL, EvidenceGateStatus.MISSING}
    )
    if not blocked:
        return "全部门槛通过"
    return "；".join(f"{gate.name}:{gate.status.value}" for gate in blocked)


def _gate_details(report: DecisionReport) -> tuple[str, ...]:
    values: list[str] = []
    for gate in report.gates:
        reasons = "；".join(gate.reasons[:2]) if gate.reasons else "无补充说明"
        values.append(f"{gate.name}: {gate.status.value} - {reasons}")
    return tuple(values)


def _strategy_mode_label(mode: StrategyMode) -> str:
    if mode is StrategyMode.LONG_TERM:
        return "长线策略"
    return "短线策略"


def _strategy_mode_description(mode: StrategyMode) -> str:
    if mode is StrategyMode.LONG_TERM:
        return "63-252个交易日，低频，重点看趋势、相对强弱、回撤和波动稳定性。"
    return "5-21个交易日，较高频，重点看短期动量、成交量确认和回撤风险。"


def _mode_label_from_strategy(report: AnalysisReport) -> str:
    if "long_term" in report.strategy_id or "long" in report.strategy_version:
        return "长线策略"
    if "short_term" in report.strategy_id or "short" in report.strategy_version:
        return "短线策略"
    return "--"


def _asset_scope_from_strategy(report: AnalysisReport) -> str:
    if "long_term" in report.strategy_id:
        return "A股、ETF、指数、黄金/债券/海外ETF；优先长期日线样本。"
    if "short_term" in report.strategy_id:
        return "A股、ETF、指数、行业主题、黄金/债券/海外ETF；优先高流动性标的。"
    return "A股、ETF、指数、基金等可取得K线/净值的标的。"


def _core_indicators_from_strategy(report: AnalysisReport) -> tuple[str, ...]:
    if "long_term" in report.strategy_id:
        return ("中长期趋势", "相对强弱", "回撤", "波动稳定性", "滚动校准")
    if "short_term" in report.strategy_id:
        return ("短中期动量", "成交量确认", "波动/回撤", "相似区间预测", "样本外回测")
    return ("动量", "趋势", "波动", "回撤", "样本外回测")


def _sample_count_from_report(report: AnalysisReport) -> str:
    snapshot = report.data_snapshot_id
    if ":" in snapshot:
        _, _, rest = snapshot.partition(":")
        bars, _, _suffix = rest.partition("-")
        if bars.isdigit():
            return f"{bars} bars"
    return "--"


def _validation_metrics_from_report(report: AnalysisReport) -> str:
    hints = [
        value
        for value in (*report.positive_drivers, *report.negative_drivers)
        if value.startswith("滚动校准") or "Brier" in value or "覆盖率" in value
    ]
    if hints:
        return "；".join(hints[:2])
    return "校准样本不足或暂未生成。"


def _grade_description(grade: str | None) -> str:
    match grade:
        case "A":
            return "A：预测、回测、校准、风险门槛均较强。"
        case "B":
            return "B：预测和历史证据可研究使用，但仍需模拟盘确认。"
        case "C":
            return "C：证据偏弱，只能观察。"
        case "N":
            return "N：不交易或样本不足。"
        case _:
            return "--"


def _format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _horizon_label(horizon: HorizonPreset) -> str:
    match horizon:
        case HorizonPreset.ONE_MONTH:
            return "1个月"
        case HorizonPreset.THREE_MONTHS:
            return "3个月"
        case HorizonPreset.SIX_MONTHS:
            return "6个月"
        case HorizonPreset.ONE_YEAR:
            return "1年"


def _backtest_summary(result: ProfitBacktestResult) -> str:
    if result.status is ProfitValidationStatus.PASS:
        prefix = "样本外验证通过"
    elif result.status is ProfitValidationStatus.INSUFFICIENT_HISTORY:
        prefix = "历史样本不足"
    elif result.status is ProfitValidationStatus.WATCH:
        prefix = "研究观察"
    else:
        prefix = "验证未通过"
    return (
        f"{prefix}：净收益{_format_percent(result.total_return)}，"
        f"最大回撤{_format_percent(result.max_drawdown)}，"
        f"超额{_format_percent(result.excess_return)}，"
        f"交易{result.trade_count}次。"
    )


def _profit_trade_summaries(result: ProfitBacktestResult) -> tuple[str, ...]:
    values: list[str] = []
    for index, trade in enumerate(result.trades, start=1):
        values.append(
            f"{index}. 买入 {trade.entry_date.isoformat()} @ {trade.entry_price:.3f}；"
            f"卖出 {trade.exit_date.isoformat()} @ {trade.exit_price:.3f}；"
            f"收益 {_format_percent(trade.net_return)}；原因 {trade.exit_reason}"
        )
    return tuple(values)


def _format_signed_percent(value: float) -> str:
    return f"{value * 100:+.2f}%"


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


def _default_market_index_states(*, status: str) -> tuple[MarketIndexPanelState, ...]:
    return (
        MarketIndexPanelState.placeholder(
            security_id="SSE:000001",
            name="上证指数",
            status=status,
        ),
        MarketIndexPanelState.placeholder(
            security_id="SZSE:399001",
            name="深证成指",
            status=status,
        ),
    )


def _knowledge_body(topic: HelpTopic) -> str:
    warnings = "；".join(topic.warnings)
    related = "、".join(topic.related_terms)
    return "\n".join(
        (
            topic.summary,
            topic.theory_context,
            topic.china_rule_context,
            topic.body,
            f"相关术语：{related}" if related else "相关术语：--",
            f"边界：{warnings}",
        )
    )


def _fallback_applicable_conditions(report: AnalysisReport) -> tuple[str, ...]:
    if report.final_signal is FinalSignal.ABSTAIN:
        return ("No new trade while the report is abstaining.",)
    return ("Data, rule, and risk gates are required before execution.",)


__all__ = [
    "AnalysisPanelState",
    "AppUiState",
    "BacktestPanelState",
    "ChartOverlay",
    "ChartPointState",
    "ChartSignalAction",
    "ChartSignalMarkerState",
    "ChartRangePreset",
    "ChartState",
    "DecisionPanelState",
    "ForecastPanelState",
    "KnowledgeCenterState",
    "KnowledgeTopicState",
    "MarketIndexPanelState",
    "MarketOverviewPanelState",
    "OperationPanelState",
    "RecentSecurityState",
    "SearchCandidateState",
    "StrategyControlState",
    "StrategyMode",
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
