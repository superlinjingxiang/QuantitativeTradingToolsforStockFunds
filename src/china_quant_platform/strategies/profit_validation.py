"""Profit-oriented ETF validation strategy and walk-forward evidence models."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from china_quant_platform.decision.models import ProfitabilityEvidence
from china_quant_platform.domain import AssetType, Bar, Exchange
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import NonEmptyString


class HorizonPreset(StrEnum):
    ONE_MONTH = "1m"
    THREE_MONTHS = "3m"
    SIX_MONTHS = "6m"
    ONE_YEAR = "1y"


class ProfitValidationStatus(StrEnum):
    PASS = "PASS"
    WATCH = "WATCH"
    FAIL = "FAIL"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


class ReliabilityGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    N = "N"


class DefaultValidationSecurity(DomainModel):
    security_id: NonEmptyString
    symbol: NonEmptyString
    name: NonEmptyString
    asset_type: AssetType
    exchange: Exchange
    asset_bucket: NonEmptyString


DEFAULT_ETF_VALIDATION_UNIVERSE: tuple[DefaultValidationSecurity, ...] = (
    DefaultValidationSecurity(
        security_id="SSE:510300",
        symbol="510300",
        name="沪深300ETF",
        asset_type=AssetType.ETF,
        exchange=Exchange.SSE,
        asset_bucket="broad_cn",
    ),
    DefaultValidationSecurity(
        security_id="SSE:513300",
        symbol="513300",
        name="纳指ETF",
        asset_type=AssetType.ETF,
        exchange=Exchange.SSE,
        asset_bucket="overseas_equity",
    ),
    DefaultValidationSecurity(
        security_id="SZSE:159915",
        symbol="159915",
        name="创业板ETF",
        asset_type=AssetType.ETF,
        exchange=Exchange.SZSE,
        asset_bucket="growth_cn",
    ),
    DefaultValidationSecurity(
        security_id="SSE:512100",
        symbol="512100",
        name="中证1000ETF",
        asset_type=AssetType.ETF,
        exchange=Exchange.SSE,
        asset_bucket="small_mid_cn",
    ),
    DefaultValidationSecurity(
        security_id="SSE:510500",
        symbol="510500",
        name="中证500ETF",
        asset_type=AssetType.ETF,
        exchange=Exchange.SSE,
        asset_bucket="mid_cn",
    ),
    DefaultValidationSecurity(
        security_id="SSE:512880",
        symbol="512880",
        name="证券ETF",
        asset_type=AssetType.ETF,
        exchange=Exchange.SSE,
        asset_bucket="sector_financials",
    ),
    DefaultValidationSecurity(
        security_id="SSE:515790",
        symbol="515790",
        name="光伏ETF",
        asset_type=AssetType.ETF,
        exchange=Exchange.SSE,
        asset_bucket="sector_solar",
    ),
    DefaultValidationSecurity(
        security_id="SSE:516160",
        symbol="516160",
        name="新能源ETF",
        asset_type=AssetType.ETF,
        exchange=Exchange.SSE,
        asset_bucket="sector_new_energy",
    ),
    DefaultValidationSecurity(
        security_id="SSE:518880",
        symbol="518880",
        name="黄金ETF",
        asset_type=AssetType.ETF,
        exchange=Exchange.SSE,
        asset_bucket="gold",
    ),
    DefaultValidationSecurity(
        security_id="SSE:511010",
        symbol="511010",
        name="国债ETF",
        asset_type=AssetType.ETF,
        exchange=Exchange.SSE,
        asset_bucket="bond",
    ),
)


DEFAULT_MIXED_VALIDATION_UNIVERSE: tuple[DefaultValidationSecurity, ...] = (
    DefaultValidationSecurity(
        security_id="SSE:600519",
        symbol="600519",
        name="贵州茅台",
        asset_type=AssetType.STOCK,
        exchange=Exchange.SSE,
        asset_bucket="stock_consumer",
    ),
    DefaultValidationSecurity(
        security_id="SSE:600036",
        symbol="600036",
        name="招商银行",
        asset_type=AssetType.STOCK,
        exchange=Exchange.SSE,
        asset_bucket="stock_financials",
    ),
    DefaultValidationSecurity(
        security_id="SSE:601318",
        symbol="601318",
        name="中国平安",
        asset_type=AssetType.STOCK,
        exchange=Exchange.SSE,
        asset_bucket="stock_insurance",
    ),
    DefaultValidationSecurity(
        security_id="SSE:600276",
        symbol="600276",
        name="恒瑞医药",
        asset_type=AssetType.STOCK,
        exchange=Exchange.SSE,
        asset_bucket="stock_healthcare",
    ),
    DefaultValidationSecurity(
        security_id="SZSE:000333",
        symbol="000333",
        name="美的集团",
        asset_type=AssetType.STOCK,
        exchange=Exchange.SZSE,
        asset_bucket="stock_manufacturing",
    ),
    *(
        member
        for member in DEFAULT_ETF_VALIDATION_UNIVERSE
        if member.security_id
        in {
            "SSE:510300",
            "SZSE:159915",
            "SSE:513300",
            "SSE:518880",
            "SSE:511010",
        }
    ),
)


class HorizonParameters(DomainModel):
    horizon: HorizonPreset
    short_lookback: int = Field(ge=1)
    long_lookback: int = Field(ge=1)
    trend_window: int = Field(ge=1)
    volatility_window: int = Field(ge=2)
    holding_days: int = Field(ge=1)

    @property
    def warmup_bars(self) -> int:
        return max(self.short_lookback, self.long_lookback, self.trend_window) + 1


class ProfitSeekingConfig(DomainModel):
    horizon: HorizonPreset = HorizonPreset.ONE_MONTH
    max_trades_per_year: int = Field(default=12, ge=1, le=252)
    round_trip_cost_bps: float = Field(default=15.0, ge=0)
    max_annual_volatility: float = Field(default=0.65, gt=0)
    min_volume_confirmation: float = Field(default=0.80, ge=0)
    min_liquidity_confirmation: float = Field(default=0.30, ge=0, le=1)
    max_short_momentum_for_entry: float = Field(default=1.0, gt=0, le=1)
    minimum_trend_efficiency: float = Field(default=0.10, ge=0, le=1)
    stop_loss_pct: float = Field(default=0.12, gt=0, le=1)
    final_test_fraction: float = Field(default=0.25, gt=0, lt=1)
    validation_fraction: float = Field(default=0.25, gt=0, lt=1)
    minimum_oos_bars: int = Field(default=60, ge=20)
    minimum_validation_bars: int = Field(default=60, ge=20)
    minimum_trades_for_pass: int = Field(default=3, ge=1)
    minimum_sharpe_for_pass: float = Field(default=0.75, ge=0)
    minimum_drawdown_improvement: float = Field(default=0.20, ge=0, le=1)
    threshold_candidates: tuple[float, ...] = (0.18, 0.25, 0.32, 0.40, 0.50)
    strategy_id: NonEmptyString = "strategy.etf_profit_validation"
    strategy_version: NonEmptyString = "profit-validation-v2"

    @model_validator(mode="after")
    def validate_thresholds(self) -> Self:
        if not self.threshold_candidates:
            raise ValueError("threshold_candidates must not be empty")
        if any(value < -1.0 or value > 1.0 for value in self.threshold_candidates):
            raise ValueError("threshold_candidates must stay within [-1, 1]")
        if self.final_test_fraction + self.validation_fraction >= 0.80:
            raise ValueError("validation and final test fractions leave too little training data")
        return self


class ProfitSignalFeatures(DomainModel):
    as_of: date
    score: float = Field(ge=-1, le=1)
    predicted_probability: float = Field(ge=0, le=1)
    short_momentum: float
    long_momentum: float
    trend_strength: float
    trend_efficiency: float = Field(ge=0, le=1)
    annualized_volatility: float = Field(ge=0)
    drawdown: float
    volume_ratio: float = Field(ge=0)
    liquidity_score: float = Field(ge=0, le=1)


class ProfitBacktestTrade(DomainModel):
    security_id: NonEmptyString
    entry_date: date
    exit_date: date
    entry_price: float = Field(gt=0)
    exit_price: float = Field(gt=0)
    holding_days: int = Field(ge=0)
    signal_score: float = Field(ge=-1, le=1)
    predicted_probability: float = Field(ge=0, le=1)
    gross_return: float
    net_return: float
    exit_reason: NonEmptyString


class ProfitEquityPoint(DomainModel):
    day: date
    net_asset_value: float = Field(gt=0)
    benchmark_value: float = Field(gt=0)


class ThresholdCandidateResult(DomainModel):
    threshold: float = Field(ge=-1, le=1)
    total_return: float
    excess_return: float
    max_drawdown: float
    trade_count: int = Field(ge=0)
    selection_score: float


class ThresholdSelection(DomainModel):
    selected_threshold: float = Field(ge=-1, le=1)
    validation_start: date
    validation_end: date
    candidates: tuple[ThresholdCandidateResult, ...]


class WalkForwardFoldResult(DomainModel):
    fold_id: NonEmptyString
    train_start: date
    validation_start: date
    test_start: date
    test_end: date
    selected_threshold: float = Field(ge=-1, le=1)
    total_return: float
    excess_return: float
    max_drawdown: float
    trade_count: int = Field(ge=0)


class ProfitBacktestResult(DomainModel):
    security_id: NonEmptyString
    horizon: HorizonPreset
    max_trades_per_year: int = Field(ge=1)
    start_date: date
    end_date: date
    selected_threshold: float = Field(ge=-1, le=1)
    total_return: float
    annualized_return: float
    annualized_volatility: float = Field(default=0.0, ge=0)
    sharpe_ratio: float | None = None
    calmar_ratio: float | None = None
    max_drawdown: float
    benchmark_total_return: float
    benchmark_max_drawdown: float = 0.0
    excess_return: float
    win_rate: float = Field(ge=0, le=1)
    trade_count: int = Field(ge=0)
    turnover: float = Field(ge=0)
    cost_drag: float = Field(ge=0)
    calibration_sample_count: int = Field(ge=0)
    brier_score: float | None = Field(default=None, ge=0)
    trades_per_year: dict[int, int] = Field(default_factory=dict)
    status: ProfitValidationStatus
    reliability_grade: ReliabilityGrade
    notes: tuple[NonEmptyString, ...]
    equity_curve: tuple[ProfitEquityPoint, ...]
    trades: tuple[ProfitBacktestTrade, ...]
    threshold_selection: ThresholdSelection | None = None
    walk_forward: tuple[WalkForwardFoldResult, ...] = ()
    walk_forward_active_folds: int = Field(default=0, ge=0)
    walk_forward_positive_ratio: float | None = Field(default=None, ge=0, le=1)
    walk_forward_excess_ratio: float | None = Field(default=None, ge=0, le=1)
    walk_forward_median_return: float | None = None
    walk_forward_median_excess: float | None = None
    checksum: NonEmptyString


class ProfitValidationAggregate(DomainModel):
    security_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    average_total_return: float
    median_total_return: float
    average_excess_return: float
    average_max_drawdown: float
    average_win_rate: float = Field(ge=0, le=1)
    total_trade_count: int = Field(ge=0)
    average_brier_score: float | None = Field(default=None, ge=0)
    status: ProfitValidationStatus
    notes: tuple[NonEmptyString, ...]


class ProfitValidationReport(DomainModel):
    config: ProfitSeekingConfig
    universe: tuple[DefaultValidationSecurity, ...]
    results: tuple[ProfitBacktestResult, ...]
    aggregate: ProfitValidationAggregate
    checksum: NonEmptyString


@dataclass(frozen=True, slots=True)
class _PendingEntry:
    features: ProfitSignalFeatures


@dataclass(frozen=True, slots=True)
class _OpenPosition:
    entry_index: int
    entry_date: date
    entry_price: float
    shares: float
    signal_score: float
    predicted_probability: float
    trailing_peak: float


def horizon_parameters(horizon: HorizonPreset) -> HorizonParameters:
    match horizon:
        case HorizonPreset.ONE_MONTH:
            return HorizonParameters(
                horizon=horizon,
                short_lookback=21,
                long_lookback=63,
                trend_window=60,
                volatility_window=20,
                holding_days=21,
            )
        case HorizonPreset.THREE_MONTHS:
            return HorizonParameters(
                horizon=horizon,
                short_lookback=63,
                long_lookback=126,
                trend_window=120,
                volatility_window=40,
                holding_days=63,
            )
        case HorizonPreset.SIX_MONTHS:
            return HorizonParameters(
                horizon=horizon,
                short_lookback=126,
                long_lookback=252,
                trend_window=200,
                volatility_window=60,
                holding_days=126,
            )
        case HorizonPreset.ONE_YEAR:
            return HorizonParameters(
                horizon=horizon,
                short_lookback=252,
                long_lookback=504,
                trend_window=252,
                volatility_window=80,
                holding_days=252,
            )


def profit_strategy_config(
    strategy_mode: Literal["short_term", "long_term"],
    horizon: HorizonPreset,
    max_trades_per_year: int,
) -> ProfitSeekingConfig:
    """Build the canonical strategy config shared by desktop, API, and labs."""

    parameters = horizon_parameters(horizon)
    if strategy_mode == "long_term":
        return ProfitSeekingConfig(
            horizon=horizon,
            max_trades_per_year=max_trades_per_year,
            max_annual_volatility=0.58,
            stop_loss_pct=0.18,
            minimum_oos_bars=max(120, parameters.holding_days),
            minimum_validation_bars=120,
            minimum_trades_for_pass=max(1, min(2, max_trades_per_year)),
            threshold_candidates=(0.20, 0.28, 0.36, 0.45, 0.55),
            strategy_id="strategy.profit_validation_long_term",
            strategy_version="profit-validation-long-v2",
        )
    return ProfitSeekingConfig(
        horizon=horizon,
        max_trades_per_year=max_trades_per_year,
        max_annual_volatility=0.78,
        stop_loss_pct=0.10,
        minimum_oos_bars=max(80, parameters.holding_days),
        minimum_validation_bars=80,
        minimum_trades_for_pass=max(1, min(3, max_trades_per_year)),
        threshold_candidates=(0.10, 0.14, 0.18, 0.25, 0.32, 0.40),
        strategy_id="strategy.profit_validation_short_term",
        strategy_version="profit-validation-short-v2",
    )


def default_etf_validation_universe() -> tuple[DefaultValidationSecurity, ...]:
    return DEFAULT_ETF_VALIDATION_UNIVERSE


def default_mixed_validation_universe() -> tuple[DefaultValidationSecurity, ...]:
    """Return five representative A-shares and five exchange-traded funds."""

    return DEFAULT_MIXED_VALIDATION_UNIVERSE


def run_profit_validation_lab(
    bars_by_security: Mapping[str, Sequence[Bar]],
    *,
    config: ProfitSeekingConfig | None = None,
    universe: Sequence[DefaultValidationSecurity] | None = None,
) -> ProfitValidationReport:
    active_config = config or ProfitSeekingConfig()
    active_universe = tuple(universe or DEFAULT_ETF_VALIDATION_UNIVERSE)
    results: list[ProfitBacktestResult] = []
    for member in active_universe:
        bars = bars_by_security.get(member.security_id, ())
        results.append(
            run_profit_strategy_backtest(
                member.security_id,
                bars,
                config=active_config,
                include_walk_forward=True,
            )
        )
    result_tuple = tuple(results)
    aggregate = _aggregate_results(result_tuple)
    checksum = _validation_checksum(active_config, active_universe, result_tuple, aggregate)
    return ProfitValidationReport(
        config=active_config,
        universe=active_universe,
        results=result_tuple,
        aggregate=aggregate,
        checksum=checksum,
    )


def run_profit_strategy_backtest(
    security_id: str,
    bars: Sequence[Bar],
    *,
    config: ProfitSeekingConfig | None = None,
    include_walk_forward: bool = False,
) -> ProfitBacktestResult:
    active_config = config or ProfitSeekingConfig()
    sorted_bars = _sorted_bars(security_id, bars)
    parameters = horizon_parameters(active_config.horizon)
    if len(sorted_bars) < _minimum_required_bars(active_config, parameters):
        return _insufficient_history_result(
            security_id=security_id,
            bars=sorted_bars,
            config=active_config,
            note=(
                f"历史K线不足：{len(sorted_bars)}/"
                f"{_minimum_required_bars(active_config, parameters)}。"
            ),
        )

    final_start = _final_oos_start_index(len(sorted_bars), active_config, parameters)
    selection = select_profit_threshold(
        security_id,
        sorted_bars,
        config=active_config,
        final_start_index=final_start,
    )
    result = _simulate_strategy(
        security_id=security_id,
        bars=sorted_bars,
        config=active_config,
        parameters=parameters,
        start_index=final_start,
        end_index=len(sorted_bars) - 1,
        threshold=selection.selected_threshold,
        threshold_selection=selection,
    )
    if include_walk_forward:
        folds = walk_forward_validate_profit_strategy(
            security_id,
            sorted_bars,
            config=active_config,
        )
        result = _apply_walk_forward_evidence(result, folds, config=active_config)
    return result


def select_profit_threshold(
    security_id: str,
    bars: Sequence[Bar],
    *,
    config: ProfitSeekingConfig | None = None,
    final_start_index: int | None = None,
) -> ThresholdSelection:
    active_config = config or ProfitSeekingConfig()
    sorted_bars = _sorted_bars(security_id, bars)
    parameters = horizon_parameters(active_config.horizon)
    if len(sorted_bars) < parameters.warmup_bars + active_config.minimum_validation_bars:
        selected = active_config.threshold_candidates[0]
        return ThresholdSelection(
            selected_threshold=selected,
            validation_start=sorted_bars[0].trade_date,
            validation_end=sorted_bars[-1].trade_date,
            candidates=(
                ThresholdCandidateResult(
                    threshold=selected,
                    total_return=0.0,
                    excess_return=0.0,
                    max_drawdown=0.0,
                    trade_count=0,
                    selection_score=-1.0,
                ),
            ),
        )

    final_start = (
        final_start_index
        if final_start_index is not None
        else _final_oos_start_index(len(sorted_bars), active_config, parameters)
    )
    validation_bars = max(
        active_config.minimum_validation_bars,
        int(final_start * active_config.validation_fraction),
    )
    validation_start = max(parameters.warmup_bars, final_start - validation_bars)
    validation_end = max(validation_start + 1, final_start - 1)
    candidates: list[ThresholdCandidateResult] = []
    for threshold in active_config.threshold_candidates:
        result = _simulate_strategy(
            security_id=security_id,
            bars=sorted_bars,
            config=active_config,
            parameters=parameters,
            start_index=validation_start,
            end_index=validation_end,
            threshold=threshold,
            threshold_selection=None,
        )
        candidates.append(
            ThresholdCandidateResult(
                threshold=threshold,
                total_return=result.total_return,
                excess_return=result.excess_return,
                max_drawdown=result.max_drawdown,
                trade_count=result.trade_count,
                selection_score=_candidate_selection_score(result, active_config),
            )
        )

    candidate_tuple = tuple(candidates)
    selected_candidate = max(
        candidate_tuple,
        key=lambda item: (
            item.selection_score,
            item.total_return,
            -abs(item.trade_count - active_config.max_trades_per_year),
            -item.threshold,
        ),
    )
    return ThresholdSelection(
        selected_threshold=selected_candidate.threshold,
        validation_start=sorted_bars[validation_start].trade_date,
        validation_end=sorted_bars[validation_end].trade_date,
        candidates=candidate_tuple,
    )


def walk_forward_validate_profit_strategy(
    security_id: str,
    bars: Sequence[Bar],
    *,
    config: ProfitSeekingConfig | None = None,
) -> tuple[WalkForwardFoldResult, ...]:
    active_config = config or ProfitSeekingConfig()
    sorted_bars = _sorted_bars(security_id, bars)
    parameters = horizon_parameters(active_config.horizon)
    train_bars = max(parameters.warmup_bars + active_config.minimum_validation_bars, 252)
    validation_bars = active_config.minimum_validation_bars
    test_bars = max(active_config.minimum_oos_bars, parameters.holding_days)
    fold_span = train_bars + validation_bars + test_bars
    if len(sorted_bars) < fold_span:
        return ()

    folds: list[WalkForwardFoldResult] = []
    step = test_bars
    start = 0
    fold_number = 1
    while start + fold_span <= len(sorted_bars):
        train_start = start
        validation_start = start + train_bars
        test_start = validation_start + validation_bars
        test_end = test_start + test_bars - 1
        training_slice = sorted_bars[train_start:test_start]
        selection = select_profit_threshold(
            security_id,
            training_slice,
            config=active_config,
            final_start_index=validation_start - train_start,
        )
        result = _simulate_strategy(
            security_id=security_id,
            bars=sorted_bars,
            config=active_config,
            parameters=parameters,
            start_index=test_start,
            end_index=test_end,
            threshold=selection.selected_threshold,
            threshold_selection=None,
        )
        folds.append(
            WalkForwardFoldResult(
                fold_id=f"fold-{fold_number:02d}",
                train_start=sorted_bars[train_start].trade_date,
                validation_start=sorted_bars[validation_start].trade_date,
                test_start=sorted_bars[test_start].trade_date,
                test_end=sorted_bars[test_end].trade_date,
                selected_threshold=selection.selected_threshold,
                total_return=result.total_return,
                excess_return=result.excess_return,
                max_drawdown=result.max_drawdown,
                trade_count=result.trade_count,
            )
        )
        fold_number += 1
        start += step
    return tuple(folds)


def profitability_evidence_from_validation(
    report: ProfitValidationReport,
    *,
    security_id: str | None = None,
) -> ProfitabilityEvidence:
    if security_id is not None:
        result = next(item for item in report.results if item.security_id == security_id)
        return ProfitabilityEvidence(
            source="profit_validation_oos",
            strategy_id=report.config.strategy_id,
            strategy_version=report.config.strategy_version,
            total_return=result.total_return,
            annualized_return=result.annualized_return,
            annualized_volatility=result.annualized_volatility,
            sharpe_ratio=result.sharpe_ratio,
            calmar_ratio=result.calmar_ratio,
            max_drawdown=result.max_drawdown,
            benchmark_total_return=result.benchmark_total_return,
            benchmark_max_drawdown=result.benchmark_max_drawdown,
            excess_return=result.excess_return,
            trade_count=result.trade_count,
            turnover=result.turnover,
            cost_drag=result.cost_drag,
            calibration_sample_count=result.calibration_sample_count,
            brier_score=result.brier_score,
            walk_forward_positive_ratio=result.walk_forward_positive_ratio,
            walk_forward_excess_ratio=result.walk_forward_excess_ratio,
            walk_forward_median_return=result.walk_forward_median_return,
            checksum=result.checksum,
            notes=(
                f"{result.horizon.value}周期样本外结果；"
                f"每年最大交易次数={result.max_trades_per_year}。",
            ),
        )

    aggregate = report.aggregate
    average_brier = aggregate.average_brier_score
    return ProfitabilityEvidence(
        source="profit_validation_lab",
        strategy_id=report.config.strategy_id,
        strategy_version=report.config.strategy_version,
        total_return=aggregate.average_total_return,
        annualized_return=None,
        max_drawdown=aggregate.average_max_drawdown,
        benchmark_total_return=0.0,
        excess_return=aggregate.average_excess_return,
        trade_count=aggregate.total_trade_count,
        turnover=None,
        cost_drag=sum(result.cost_drag for result in report.results),
        calibration_sample_count=sum(result.calibration_sample_count for result in report.results),
        brier_score=average_brier,
        checksum=report.checksum,
        notes=("十标的ETF样本外验证聚合证据；平均收益为横截面平均，不代表保证收益。",),
    )


def _simulate_strategy(
    *,
    security_id: str,
    bars: Sequence[Bar],
    config: ProfitSeekingConfig,
    parameters: HorizonParameters,
    start_index: int,
    end_index: int,
    threshold: float,
    threshold_selection: ThresholdSelection | None,
) -> ProfitBacktestResult:
    if end_index <= start_index:
        return _insufficient_history_result(
            security_id=security_id,
            bars=bars,
            config=config,
            note="样本外区间为空，无法验证。",
        )

    closes = tuple(bar.close_price for bar in bars)
    cash = 1.0
    position: _OpenPosition | None = None
    pending_entry: _PendingEntry | None = None
    last_entry_index = -10_000
    entries_per_year: dict[int, int] = {}
    trades: list[ProfitBacktestTrade] = []
    equity_curve: list[ProfitEquityPoint] = []
    half_cost_rate = config.round_trip_cost_bps / 20_000.0
    benchmark_start = bars[start_index].close_price
    benchmark_value = 1.0

    for index in range(start_index, end_index + 1):
        bar = bars[index]
        if pending_entry is not None and position is None:
            position = _open_position(
                index=index,
                bar=bar,
                cash=cash,
                half_cost_rate=half_cost_rate,
                pending_entry=pending_entry,
            )
            cash = 0.0
            last_entry_index = index
            entries_per_year[position.entry_date.year] = (
                entries_per_year.get(position.entry_date.year, 0) + 1
            )
            pending_entry = None

        if position is not None:
            position = position.__class__(
                entry_index=position.entry_index,
                entry_date=position.entry_date,
                entry_price=position.entry_price,
                shares=position.shares,
                signal_score=position.signal_score,
                predicted_probability=position.predicted_probability,
                trailing_peak=max(position.trailing_peak, bar.close_price),
            )
            exit_reason = _exit_reason(
                index=index,
                closes=closes,
                bar=bar,
                position=position,
                parameters=parameters,
                config=config,
            )
            if exit_reason is not None:
                cash, trade = _close_position(
                    security_id=security_id,
                    index=index,
                    bar=bar,
                    position=position,
                    half_cost_rate=half_cost_rate,
                    exit_reason=exit_reason,
                )
                trades.append(trade)
                position = None

        nav = cash if position is None else position.shares * bar.close_price
        benchmark_value = 1.0 if benchmark_start <= 0 else bar.close_price / benchmark_start
        equity_curve.append(
            ProfitEquityPoint(
                day=bar.trade_date,
                net_asset_value=max(nav, 1e-12),
                benchmark_value=max(benchmark_value, 1e-12),
            )
        )

        next_index = index + 1
        if (
            position is None
            and pending_entry is None
            and next_index <= end_index
            and _can_enter(
                index=index,
                next_index=next_index,
                last_entry_index=last_entry_index,
                entries_per_year=entries_per_year,
                bars=bars,
                config=config,
            )
        ):
            features = _signal_features(index, bars=bars, closes=closes, parameters=parameters)
            if features is not None and _entry_signal_passes(
                features,
                threshold=threshold,
                config=config,
            ):
                pending_entry = _PendingEntry(features=features)

    if position is not None:
        final_bar = bars[end_index]
        cash, trade = _close_position(
            security_id=security_id,
            index=end_index,
            bar=final_bar,
            position=position,
            half_cost_rate=half_cost_rate,
            exit_reason="end_of_sample_liquidation",
        )
        trades.append(trade)
        if equity_curve:
            equity_curve[-1] = equity_curve[-1].model_copy(
                update={"net_asset_value": max(cash, 1e-12)}
            )

    return _build_result(
        security_id=security_id,
        bars=bars,
        config=config,
        start_index=start_index,
        end_index=end_index,
        threshold=threshold,
        trades=tuple(trades),
        equity_curve=tuple(equity_curve),
        trades_per_year=entries_per_year,
        threshold_selection=threshold_selection,
    )


def _open_position(
    *,
    index: int,
    bar: Bar,
    cash: float,
    half_cost_rate: float,
    pending_entry: _PendingEntry,
) -> _OpenPosition:
    entry_price = max(bar.open_price, 1e-12)
    shares = cash / (entry_price * (1.0 + half_cost_rate))
    return _OpenPosition(
        entry_index=index,
        entry_date=bar.trade_date,
        entry_price=entry_price,
        shares=shares,
        signal_score=pending_entry.features.score,
        predicted_probability=pending_entry.features.predicted_probability,
        trailing_peak=max(bar.high_price, bar.close_price, entry_price),
    )


def _close_position(
    *,
    security_id: str,
    index: int,
    bar: Bar,
    position: _OpenPosition,
    half_cost_rate: float,
    exit_reason: str,
) -> tuple[float, ProfitBacktestTrade]:
    exit_price = max(bar.close_price, 1e-12)
    cash = position.shares * exit_price * (1.0 - half_cost_rate)
    gross_return = exit_price / position.entry_price - 1.0
    net_return = (
        cash - 1.0
        if position.shares == 0
        else (exit_price * (1.0 - half_cost_rate)) / (position.entry_price * (1.0 + half_cost_rate))
        - 1.0
    )
    return cash, ProfitBacktestTrade(
        security_id=security_id,
        entry_date=position.entry_date,
        exit_date=bar.trade_date,
        entry_price=position.entry_price,
        exit_price=exit_price,
        holding_days=max(0, index - position.entry_index),
        signal_score=position.signal_score,
        predicted_probability=position.predicted_probability,
        gross_return=gross_return,
        net_return=net_return,
        exit_reason=exit_reason,
    )


def _exit_reason(
    *,
    index: int,
    closes: Sequence[float],
    bar: Bar,
    position: _OpenPosition,
    parameters: HorizonParameters,
    config: ProfitSeekingConfig,
) -> str | None:
    holding_days = index - position.entry_index
    if holding_days >= parameters.holding_days:
        return "holding_period_reached"
    if bar.close_price / position.trailing_peak - 1.0 <= -config.stop_loss_pct:
        return "stop_loss"
    features = _signal_features(index, bars=(), closes=closes, parameters=parameters)
    if features is None:
        return None
    if features.score <= -0.10:
        return "score_breakdown"
    if features.trend_strength < -0.02:
        return "trend_breakdown"
    return None


def _can_enter(
    *,
    index: int,
    next_index: int,
    last_entry_index: int,
    entries_per_year: Mapping[int, int],
    bars: Sequence[Bar],
    config: ProfitSeekingConfig,
) -> bool:
    min_entry_gap = max(1, math.ceil(252 / config.max_trades_per_year))
    if index - last_entry_index < min_entry_gap:
        return False
    next_year = bars[next_index].trade_date.year
    return entries_per_year.get(next_year, 0) < config.max_trades_per_year


def _entry_signal_passes(
    features: ProfitSignalFeatures,
    *,
    threshold: float,
    config: ProfitSeekingConfig,
) -> bool:
    return (
        features.score >= threshold
        and features.short_momentum > 0
        and features.short_momentum <= config.max_short_momentum_for_entry
        and features.long_momentum > 0
        and features.trend_strength > 0
        and features.trend_efficiency >= config.minimum_trend_efficiency
        and features.annualized_volatility <= config.max_annual_volatility
        and features.drawdown >= -0.35
        and features.volume_ratio >= config.min_volume_confirmation
        and features.liquidity_score >= config.min_liquidity_confirmation
    )


def _signal_features(
    index: int,
    *,
    bars: Sequence[Bar],
    closes: Sequence[float],
    parameters: HorizonParameters,
) -> ProfitSignalFeatures | None:
    if index < parameters.warmup_bars - 1:
        return None
    if closes[index] <= 0:
        return None
    short_base = closes[index - parameters.short_lookback]
    long_base = closes[index - parameters.long_lookback]
    if short_base <= 0 or long_base <= 0:
        return None

    short_momentum = closes[index] / short_base - 1.0
    long_momentum = closes[index] / long_base - 1.0
    trend_values = closes[index - parameters.trend_window + 1 : index + 1]
    trend_average = sum(trend_values) / len(trend_values)
    trend_strength = closes[index] / trend_average - 1.0 if trend_average > 0 else 0.0
    trend_efficiency = _trend_efficiency(closes[index - parameters.short_lookback : index + 1])
    volatility_returns = _period_returns(closes[index - parameters.volatility_window : index + 1])
    annualized_volatility = _population_std(volatility_returns) * math.sqrt(252.0)
    volume_ratio = _volume_ratio(index, bars=bars, window=parameters.volatility_window)
    liquidity_score = _liquidity_score(index, bars=bars, window=parameters.volatility_window)
    drawdown_window_start = max(0, index - parameters.long_lookback + 1)
    peak = max(closes[drawdown_window_start : index + 1])
    drawdown = closes[index] / peak - 1.0 if peak > 0 else 0.0
    score = _clamp(
        0.45 * _clamp(short_momentum / 0.12)
        + 0.30 * _clamp(long_momentum / 0.25)
        + 0.25 * _clamp(trend_strength / 0.08)
        + 0.10 * _clamp((volume_ratio - 1.0) / 0.60)
        + 0.08 * (liquidity_score * 2.0 - 1.0)
        - 0.20 * min(annualized_volatility / 0.65, 1.0)
        - 0.15 * min(abs(min(drawdown, 0.0)) / 0.25, 1.0)
    )
    as_of = bars[index].trade_date if bars else date.min
    return ProfitSignalFeatures(
        as_of=as_of,
        score=score,
        predicted_probability=max(0.05, min(0.95, 0.50 + score * 0.25)),
        short_momentum=short_momentum,
        long_momentum=long_momentum,
        trend_strength=trend_strength,
        trend_efficiency=trend_efficiency,
        annualized_volatility=annualized_volatility,
        drawdown=drawdown,
        volume_ratio=volume_ratio,
        liquidity_score=liquidity_score,
    )


def _build_result(
    *,
    security_id: str,
    bars: Sequence[Bar],
    config: ProfitSeekingConfig,
    start_index: int,
    end_index: int,
    threshold: float,
    trades: tuple[ProfitBacktestTrade, ...],
    equity_curve: tuple[ProfitEquityPoint, ...],
    trades_per_year: dict[int, int],
    threshold_selection: ThresholdSelection | None,
) -> ProfitBacktestResult:
    total_return = equity_curve[-1].net_asset_value / equity_curve[0].net_asset_value - 1.0
    benchmark_total_return = equity_curve[-1].benchmark_value / equity_curve[0].benchmark_value - 1
    daily_returns = tuple(
        current.net_asset_value / previous.net_asset_value - 1.0
        for previous, current in zip(equity_curve, equity_curve[1:], strict=False)
    )
    annualized_return = (1.0 + total_return) ** (252.0 / max(len(daily_returns), 1)) - 1.0
    annualized_volatility = _population_std(daily_returns) * math.sqrt(252.0)
    sharpe_ratio = _sharpe_ratio(daily_returns)
    max_drawdown = _max_drawdown(tuple(point.net_asset_value for point in equity_curve))
    benchmark_max_drawdown = _max_drawdown(tuple(point.benchmark_value for point in equity_curve))
    calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown < -1e-12 else None
    wins = sum(1 for trade in trades if trade.net_return > 0)
    win_rate = 0.0 if not trades else wins / len(trades)
    cost_drag = len(trades) * config.round_trip_cost_bps / 10_000.0
    turnover = float(len(trades) * 2)
    probabilities = tuple(trade.predicted_probability for trade in trades)
    outcomes = tuple(1 if trade.net_return > 0 else 0 for trade in trades)
    brier_score = _brier_score(probabilities, outcomes) if probabilities else None
    status = _validation_status(
        total_return=total_return,
        excess_return=total_return - benchmark_total_return,
        max_drawdown=max_drawdown,
        benchmark_max_drawdown=benchmark_max_drawdown,
        sharpe_ratio=sharpe_ratio,
        trade_count=len(trades),
        config=config,
    )
    grade = _reliability_grade(
        total_return=total_return,
        excess_return=total_return - benchmark_total_return,
        max_drawdown=max_drawdown,
        win_rate=win_rate,
        trade_count=len(trades),
        status=status,
    )
    result = ProfitBacktestResult(
        security_id=security_id,
        horizon=config.horizon,
        max_trades_per_year=config.max_trades_per_year,
        start_date=bars[start_index].trade_date,
        end_date=bars[end_index].trade_date,
        selected_threshold=threshold,
        total_return=total_return,
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        sharpe_ratio=sharpe_ratio,
        calmar_ratio=calmar_ratio,
        max_drawdown=max_drawdown,
        benchmark_total_return=benchmark_total_return,
        benchmark_max_drawdown=benchmark_max_drawdown,
        excess_return=total_return - benchmark_total_return,
        win_rate=win_rate,
        trade_count=len(trades),
        turnover=turnover,
        cost_drag=cost_drag,
        calibration_sample_count=len(outcomes),
        brier_score=brier_score,
        trades_per_year=trades_per_year,
        status=status,
        reliability_grade=grade,
        notes=_result_notes(status=status, trade_count=len(trades), config=config),
        equity_curve=equity_curve,
        trades=trades,
        threshold_selection=threshold_selection,
        checksum="pending",
    )
    return result.model_copy(update={"checksum": _result_checksum(result)})


def _validation_status(
    *,
    total_return: float,
    excess_return: float,
    max_drawdown: float,
    benchmark_max_drawdown: float,
    sharpe_ratio: float | None,
    trade_count: int,
    config: ProfitSeekingConfig,
) -> ProfitValidationStatus:
    if trade_count < config.minimum_trades_for_pass:
        return ProfitValidationStatus.WATCH
    drawdown_improved = benchmark_max_drawdown < -1e-12 and abs(max_drawdown) <= abs(
        benchmark_max_drawdown
    ) * (1.0 - config.minimum_drawdown_improvement)
    risk_adjusted_pass = (
        sharpe_ratio is not None
        and sharpe_ratio >= config.minimum_sharpe_for_pass
        and drawdown_improved
    )
    if total_return > 0 and (excess_return > 0 or risk_adjusted_pass) and abs(max_drawdown) <= 0.25:
        return ProfitValidationStatus.PASS
    if total_return > 0 and abs(max_drawdown) <= 0.35:
        return ProfitValidationStatus.WATCH
    return ProfitValidationStatus.FAIL


def _reliability_grade(
    *,
    total_return: float,
    excess_return: float,
    max_drawdown: float,
    win_rate: float,
    trade_count: int,
    status: ProfitValidationStatus,
) -> ReliabilityGrade:
    if status is ProfitValidationStatus.PASS:
        if total_return >= 0.12 and excess_return >= 0.04 and abs(max_drawdown) <= 0.12:
            return ReliabilityGrade.A
        if win_rate >= 0.50 and trade_count >= 3:
            return ReliabilityGrade.B
        return ReliabilityGrade.C
    if status is ProfitValidationStatus.WATCH:
        return ReliabilityGrade.C
    return ReliabilityGrade.N


def _result_notes(
    *,
    status: ProfitValidationStatus,
    trade_count: int,
    config: ProfitSeekingConfig,
) -> tuple[str, ...]:
    notes = [
        "收益为扣除简化往返成本后的历史样本外结果，不代表保证未来收益。",
        f"交易次数按每年最大{config.max_trades_per_year}次约束。",
        "入场同时检查动量、趋势、波动、回撤、成交量确认和流动性，避免只凭价格追涨。",
    ]
    if config.max_short_momentum_for_entry < 1.0:
        notes.append(f"短期动量超过{config.max_short_momentum_for_entry:.0%}视为过热，不追涨入场。")
    if config.minimum_trend_efficiency > 0:
        notes.append(f"趋势效率低于{config.minimum_trend_efficiency:.0%}时不入场。")
    if status is ProfitValidationStatus.PASS:
        notes.append("样本外净收益、回撤及正超额或风险调整比较暂时通过。")
    elif trade_count < config.minimum_trades_for_pass:
        notes.append("样本外交易次数不足，不能证明通用赚钱能力。")
    else:
        notes.append("样本外收益、回撤或基准比较未全部通过。")
    return tuple(notes)


def _apply_walk_forward_evidence(
    result: ProfitBacktestResult,
    folds: tuple[WalkForwardFoldResult, ...],
    *,
    config: ProfitSeekingConfig,
) -> ProfitBacktestResult:
    active = tuple(fold for fold in folds if fold.trade_count > 0)
    if not active:
        status = (
            ProfitValidationStatus.FAIL
            if result.status is ProfitValidationStatus.FAIL
            else ProfitValidationStatus.WATCH
        )
        notes = (*result.notes, "滚动前推没有形成有效交易折，盈利证据降级。")
        updated = result.model_copy(
            update={
                "walk_forward": folds,
                "walk_forward_active_folds": 0,
                "status": status,
                "reliability_grade": (
                    ReliabilityGrade.N
                    if status is ProfitValidationStatus.FAIL
                    else ReliabilityGrade.C
                ),
                "notes": notes,
            }
        )
        return updated.model_copy(update={"checksum": _result_checksum(updated)})

    positive_ratio = sum(fold.total_return > 0 for fold in active) / len(active)
    excess_ratio = sum(fold.excess_return > 0 for fold in active) / len(active)
    median_return = _median(tuple(fold.total_return for fold in active))
    median_excess = _median(tuple(fold.excess_return for fold in active))
    consistent = len(active) >= 5 and positive_ratio >= 0.55 and median_return > 0
    status = result.status
    if status is ProfitValidationStatus.PASS and not consistent:
        status = ProfitValidationStatus.WATCH
    grade = _reliability_grade(
        total_return=result.total_return,
        excess_return=result.excess_return,
        max_drawdown=result.max_drawdown,
        win_rate=result.win_rate,
        trade_count=result.trade_count,
        status=status,
    )
    if status is ProfitValidationStatus.PASS and positive_ratio >= 0.70:
        grade = (
            ReliabilityGrade.A
            if result.sharpe_ratio is not None and result.sharpe_ratio >= 0.80
            else ReliabilityGrade.B
        )
    notes = (
        *result.notes,
        (
            f"滚动前推有效{len(active)}/{len(folds)}折，"
            f"正收益折{positive_ratio:.0%}，超额为正折{excess_ratio:.0%}，"
            f"折中位收益{median_return:.2%}。"
        ),
    )
    if result.status is ProfitValidationStatus.PASS and status is ProfitValidationStatus.WATCH:
        notes = (*notes, "最终留出区间虽通过，但跨窗口一致性不足，状态降为WATCH。")
    updated = result.model_copy(
        update={
            "walk_forward": folds,
            "walk_forward_active_folds": len(active),
            "walk_forward_positive_ratio": positive_ratio,
            "walk_forward_excess_ratio": excess_ratio,
            "walk_forward_median_return": median_return,
            "walk_forward_median_excess": median_excess,
            "status": status,
            "reliability_grade": grade,
            "notes": notes,
        }
    )
    return updated.model_copy(update={"checksum": _result_checksum(updated)})


def _aggregate_results(results: Sequence[ProfitBacktestResult]) -> ProfitValidationAggregate:
    valid_results = tuple(
        result
        for result in results
        if result.status is not ProfitValidationStatus.INSUFFICIENT_HISTORY
    )
    if not valid_results:
        return ProfitValidationAggregate(
            security_count=len(results),
            passed_count=0,
            average_total_return=0.0,
            median_total_return=0.0,
            average_excess_return=0.0,
            average_max_drawdown=0.0,
            average_win_rate=0.0,
            total_trade_count=0,
            average_brier_score=None,
            status=ProfitValidationStatus.INSUFFICIENT_HISTORY,
            notes=("全部标的历史样本不足，无法验证策略通用性。",),
        )
    total_returns = tuple(result.total_return for result in valid_results)
    brier_values = tuple(
        result.brier_score for result in valid_results if result.brier_score is not None
    )
    passed_count = sum(
        1 for result in valid_results if result.status is ProfitValidationStatus.PASS
    )
    status = (
        ProfitValidationStatus.PASS
        if passed_count >= math.ceil(len(valid_results) * 0.60)
        else ProfitValidationStatus.WATCH
        if passed_count > 0
        else ProfitValidationStatus.FAIL
    )
    return ProfitValidationAggregate(
        security_count=len(results),
        passed_count=passed_count,
        average_total_return=sum(total_returns) / len(total_returns),
        median_total_return=_median(total_returns),
        average_excess_return=sum(result.excess_return for result in valid_results)
        / len(valid_results),
        average_max_drawdown=sum(result.max_drawdown for result in valid_results)
        / len(valid_results),
        average_win_rate=sum(result.win_rate for result in valid_results) / len(valid_results),
        total_trade_count=sum(result.trade_count for result in valid_results),
        average_brier_score=(sum(brier_values) / len(brier_values) if brier_values else None),
        status=status,
        notes=_aggregate_notes(status, passed_count, len(valid_results)),
    )


def _aggregate_notes(
    status: ProfitValidationStatus,
    passed_count: int,
    result_count: int,
) -> tuple[str, ...]:
    if status is ProfitValidationStatus.PASS:
        return (
            f"{passed_count}/{result_count}个有效标的通过样本外盈利验证。",
            "仍需模拟盘偏差验证后才能提升执行候选等级。",
        )
    if passed_count:
        return (
            f"仅{passed_count}/{result_count}个有效标的通过，通用性证据不足。",
            "建议继续保持研究或观察状态。",
        )
    return ("没有有效标的通过样本外盈利验证，策略不得进入执行候选。",)


def _candidate_selection_score(
    result: ProfitBacktestResult,
    config: ProfitSeekingConfig,
) -> float:
    target_trades = max(1, min(config.max_trades_per_year, config.minimum_trades_for_pass * 2))
    trade_penalty = abs(result.trade_count - target_trades) * 0.01
    drawdown_penalty = abs(min(result.max_drawdown, 0.0)) * 0.50
    no_trade_penalty = 0.50 if result.trade_count == 0 else 0.0
    return (
        result.total_return
        + result.excess_return * 0.40
        + result.win_rate * 0.10
        - drawdown_penalty
        - trade_penalty
        - no_trade_penalty
    )


def _insufficient_history_result(
    *,
    security_id: str,
    bars: Sequence[Bar],
    config: ProfitSeekingConfig,
    note: str,
) -> ProfitBacktestResult:
    start_date = bars[0].trade_date if bars else date.min
    end_date = bars[-1].trade_date if bars else date.min
    equity_curve = (
        ProfitEquityPoint(day=start_date, net_asset_value=1.0, benchmark_value=1.0),
        ProfitEquityPoint(day=end_date, net_asset_value=1.0, benchmark_value=1.0),
    )
    result = ProfitBacktestResult(
        security_id=security_id,
        horizon=config.horizon,
        max_trades_per_year=config.max_trades_per_year,
        start_date=start_date,
        end_date=end_date,
        selected_threshold=config.threshold_candidates[0],
        total_return=0.0,
        annualized_return=0.0,
        max_drawdown=0.0,
        benchmark_total_return=0.0,
        excess_return=0.0,
        win_rate=0.0,
        trade_count=0,
        turnover=0.0,
        cost_drag=0.0,
        calibration_sample_count=0,
        brier_score=None,
        trades_per_year={},
        status=ProfitValidationStatus.INSUFFICIENT_HISTORY,
        reliability_grade=ReliabilityGrade.N,
        notes=(note,),
        equity_curve=equity_curve,
        trades=(),
        threshold_selection=None,
        checksum="pending",
    )
    return result.model_copy(update={"checksum": _result_checksum(result)})


def _minimum_required_bars(
    config: ProfitSeekingConfig,
    parameters: HorizonParameters,
) -> int:
    return parameters.warmup_bars + config.minimum_validation_bars + config.minimum_oos_bars


def _final_oos_start_index(
    bar_count: int,
    config: ProfitSeekingConfig,
    parameters: HorizonParameters,
) -> int:
    final_bars = max(config.minimum_oos_bars, int(bar_count * config.final_test_fraction))
    return max(parameters.warmup_bars, bar_count - final_bars)


def _sorted_bars(security_id: str, bars: Sequence[Bar]) -> tuple[Bar, ...]:
    return tuple(
        sorted(
            (bar for bar in bars if bar.security_id == security_id),
            key=lambda item: (item.end_time, item.trade_date),
        )
    )


def _period_returns(values: Sequence[float]) -> tuple[float, ...]:
    return tuple(
        current / previous - 1.0
        for previous, current in zip(values, values[1:], strict=False)
        if previous > 0
    )


def _volume_ratio(index: int, *, bars: Sequence[Bar], window: int) -> float:
    if not bars or index <= 0:
        return 1.0
    start = max(0, index - window)
    previous_volumes = tuple(max(bar.volume, 0.0) for bar in bars[start:index])
    if not previous_volumes:
        return 1.0
    average_volume = sum(previous_volumes) / len(previous_volumes)
    if average_volume <= 0:
        return 1.0
    return max(bars[index].volume, 0.0) / average_volume


def _liquidity_score(index: int, *, bars: Sequence[Bar], window: int) -> float:
    if not bars or index <= 0:
        return 1.0
    start = max(0, index - window)
    previous_amounts = tuple(max(bar.amount, 0.0) for bar in bars[start:index])
    if not previous_amounts:
        return 1.0
    average_amount = sum(previous_amounts) / len(previous_amounts)
    if average_amount <= 0:
        return 1.0
    return max(0.0, min(max(bars[index].amount, 0.0) / average_amount / 2.0, 1.0))


def _population_std(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _trend_efficiency(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    path = sum(
        abs(current - previous) for previous, current in zip(values, values[1:], strict=False)
    )
    if path <= 1e-12:
        return 0.0
    return max(0.0, min(abs(values[-1] - values[0]) / path, 1.0))


def _sharpe_ratio(returns: Sequence[float]) -> float | None:
    if len(returns) < 2:
        return None
    volatility = _population_std(returns)
    if volatility <= 1e-12:
        return None
    return sum(returns) / len(returns) / volatility * math.sqrt(252.0)


def _max_drawdown(values: Sequence[float]) -> float:
    peak = values[0] if values else 1.0
    drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1.0 if peak else 0.0)
    return drawdown


def _brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> float:
    return sum(
        (probability - outcome) ** 2
        for probability, outcome in zip(probabilities, outcomes, strict=True)
    ) / len(probabilities)


def _median(values: Sequence[float]) -> float:
    sorted_values = tuple(sorted(values))
    middle = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[middle]
    return (sorted_values[middle - 1] + sorted_values[middle]) / 2


def _clamp(value: float) -> float:
    return max(-1.0, min(value, 1.0))


def _result_checksum(result: ProfitBacktestResult) -> str:
    payload = result.model_copy(update={"checksum": "pending"}).to_contract_dict()
    return _stable_checksum(payload)


def _validation_checksum(
    config: ProfitSeekingConfig,
    universe: Sequence[DefaultValidationSecurity],
    results: Sequence[ProfitBacktestResult],
    aggregate: ProfitValidationAggregate,
) -> str:
    return _stable_checksum(
        {
            "config": config.to_contract_dict(),
            "universe": [member.to_contract_dict() for member in universe],
            "results": [result.to_contract_dict() for result in results],
            "aggregate": aggregate.to_contract_dict(),
        }
    )


def _stable_checksum(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()
