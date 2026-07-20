"""Point-in-time validation for a long-only ETF rotation portfolio."""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from china_quant_platform.domain import Bar
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import NonEmptyString


class EtfRotationValidationStatus(StrEnum):
    PASS = "PASS"
    WATCH = "WATCH"
    FAIL = "FAIL"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


class EtfRotationBacktestConfig(DomainModel):
    formation_lookback_bars: int = Field(default=252, ge=20)
    volatility_lookback_bars: int = Field(default=63, ge=20)
    rebalance_interval_bars: int = Field(default=21, ge=1)
    max_positions: int = Field(default=2, ge=1)
    target_annual_volatility: float = Field(default=0.20, gt=0, le=1)
    min_position_fraction: float = Field(default=0.25, ge=0, le=1)
    max_position_fraction: float = Field(default=1.0, gt=0, le=1)
    round_trip_cost_bps: float = Field(default=15.0, ge=0)
    stress_round_trip_cost_bps: float = Field(default=45.0, ge=0)
    maximum_acceptable_drawdown: float = Field(default=0.25, gt=0, le=1)
    minimum_sharpe_ratio: float = 0.75
    minimum_walk_forward_positive_ratio: float = Field(default=0.60, ge=0, le=1)
    minimum_walk_forward_excess_ratio: float = Field(default=0.50, ge=0, le=1)
    minimum_walk_forward_folds: int = Field(default=3, ge=1)
    walk_forward_window_bars: int = Field(default=252, ge=63)
    walk_forward_step_bars: int = Field(default=126, ge=21)

    @model_validator(mode="after")
    def validate_ranges(self) -> Self:
        if self.min_position_fraction > self.max_position_fraction:
            raise ValueError("min_position_fraction must not exceed max_position_fraction")
        if self.stress_round_trip_cost_bps < self.round_trip_cost_bps:
            raise ValueError("stress cost must not be lower than base cost")
        return self


class EtfRotationEquityPoint(DomainModel):
    trade_date: date
    equity: float = Field(gt=0)


class EtfRotationRebalanceEvent(DomainModel):
    signal_date: date
    execution_date: date
    selected_security_ids: tuple[NonEmptyString, ...]
    momentum_scores: dict[str, float]
    target_position_fraction: float = Field(ge=0, le=1)
    target_weights: dict[str, float] = Field(default_factory=dict)
    trade_weight_changes: dict[str, float] = Field(default_factory=dict)
    turnover_fraction: float = Field(default=0.0, ge=0, le=2)
    transaction_cost_fraction: float = Field(default=0.0, ge=0, lt=1)

    @model_validator(mode="after")
    def validate_rebalance(self) -> Self:
        if self.target_weights:
            if set(self.target_weights) != set(self.selected_security_ids):
                raise ValueError("target_weights must match selected_security_ids")
            if any(weight < 0 or weight > 1 for weight in self.target_weights.values()):
                raise ValueError("target weights must be between zero and one")
            if not math.isclose(
                sum(self.target_weights.values()),
                self.target_position_fraction,
                abs_tol=1e-9,
            ):
                raise ValueError("target weights must sum to target_position_fraction")
        if self.trade_weight_changes and not math.isclose(
            sum(abs(value) for value in self.trade_weight_changes.values()),
            self.turnover_fraction,
            abs_tol=1e-9,
        ):
            raise ValueError("trade weight changes must sum to turnover_fraction")
        return self


class EtfRotationAllocationSnapshot(DomainModel):
    as_of_date: date
    signal_date: date
    execution_date: date
    selected_security_ids: tuple[NonEmptyString, ...]
    momentum_scores: dict[str, float]
    target_position_fraction: float = Field(ge=0, le=1)
    target_weights: dict[str, float]
    bars_since_rebalance: int = Field(ge=0)
    bars_until_next_rebalance: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_allocation(self) -> Self:
        if set(self.target_weights) != set(self.selected_security_ids):
            raise ValueError("target_weights must match selected_security_ids")
        if any(weight < 0 or weight > 1 for weight in self.target_weights.values()):
            raise ValueError("target weights must be between zero and one")
        if not math.isclose(
            sum(self.target_weights.values()),
            self.target_position_fraction,
            abs_tol=1e-9,
        ):
            raise ValueError("target weights must sum to target_position_fraction")
        return self


class EtfRotationBacktestResult(DomainModel):
    evaluation_start: date
    evaluation_end: date
    total_return: float
    annualized_return: float
    max_drawdown: float = Field(le=0)
    sharpe_ratio: float
    equal_weight_benchmark_return: float
    excess_return: float
    rebalance_count: int = Field(ge=0)
    active_rebalance_count: int = Field(ge=0)
    average_position_fraction: float = Field(ge=0, le=1)
    cumulative_turnover: float = Field(ge=0)
    average_rebalance_turnover: float = Field(ge=0, le=2)
    cumulative_transaction_cost: float = Field(ge=0)
    round_trip_cost_bps: float = Field(ge=0)
    selection_counts: dict[str, int]
    equity_curve: tuple[EtfRotationEquityPoint, ...]
    rebalances: tuple[EtfRotationRebalanceEvent, ...]


class EtfRotationWalkForwardFold(DomainModel):
    fold_id: NonEmptyString
    evaluation_start: date
    evaluation_end: date
    total_return: float
    excess_return: float
    max_drawdown: float
    sharpe_ratio: float


class EtfRotationValidationReport(DomainModel):
    status: EtfRotationValidationStatus
    config: EtfRotationBacktestConfig
    base: EtfRotationBacktestResult
    stress: EtfRotationBacktestResult
    walk_forward_folds: tuple[EtfRotationWalkForwardFold, ...]
    walk_forward_positive_ratio: float = Field(ge=0, le=1)
    walk_forward_excess_ratio: float = Field(ge=0, le=1)
    notes: tuple[NonEmptyString, ...]


def build_current_etf_rotation_allocation(
    bars_by_security: Mapping[str, Sequence[Bar]],
    *,
    security_ids: Sequence[str],
    config: EtfRotationBacktestConfig | None = None,
) -> EtfRotationAllocationSnapshot:
    """Return the latest scheduled allocation from the same path as the backtest."""

    active_config = config or EtfRotationBacktestConfig()
    identifiers = tuple(dict.fromkeys(security_ids))
    result = run_etf_rotation_backtest(
        bars_by_security,
        security_ids=identifiers,
        config=active_config,
    )
    if not result.rebalances:
        raise ValueError("ETF rotation has no completed rebalance event")
    latest = result.rebalances[-1]
    common_dates = sorted(
        set.intersection(
            *(
                {bar.trade_date for bar in bars_by_security[security_id]}
                for security_id in identifiers
            )
        )
    )
    execution_index = common_dates.index(latest.execution_date)
    as_of_index = common_dates.index(result.evaluation_end)
    bars_since_rebalance = as_of_index - execution_index
    bars_until_next_rebalance = max(
        1,
        active_config.rebalance_interval_bars - bars_since_rebalance,
    )
    target_weights = latest.target_weights
    if not target_weights and latest.selected_security_ids:
        per_security_weight = latest.target_position_fraction / len(latest.selected_security_ids)
        target_weights = {
            security_id: per_security_weight for security_id in latest.selected_security_ids
        }
    return EtfRotationAllocationSnapshot(
        as_of_date=result.evaluation_end,
        signal_date=latest.signal_date,
        execution_date=latest.execution_date,
        selected_security_ids=latest.selected_security_ids,
        momentum_scores=latest.momentum_scores,
        target_position_fraction=latest.target_position_fraction,
        target_weights=target_weights,
        bars_since_rebalance=bars_since_rebalance,
        bars_until_next_rebalance=bars_until_next_rebalance,
    )


def run_etf_rotation_backtest(
    bars_by_security: Mapping[str, Sequence[Bar]],
    *,
    security_ids: Sequence[str],
    config: EtfRotationBacktestConfig | None = None,
    evaluation_start: date | None = None,
    evaluation_end: date | None = None,
) -> EtfRotationBacktestResult:
    active_config = config or EtfRotationBacktestConfig()
    identifiers = tuple(dict.fromkeys(security_ids))
    if len(identifiers) < active_config.max_positions:
        raise ValueError("ETF universe must contain at least max_positions securities")
    missing = [security_id for security_id in identifiers if not bars_by_security.get(security_id)]
    if missing:
        raise ValueError(f"missing ETF bars: {', '.join(missing)}")

    indexed = {
        security_id: {bar.trade_date: bar for bar in bars_by_security[security_id]}
        for security_id in identifiers
    }
    common_dates = sorted(set.intersection(*(set(items) for items in indexed.values())))
    warmup = (
        max(
            active_config.formation_lookback_bars,
            active_config.volatility_lookback_bars,
        )
        + 1
    )
    if len(common_dates) <= warmup + 1:
        raise ValueError(f"insufficient common ETF history: {len(common_dates)}/{warmup + 2}")

    start_index = warmup
    if evaluation_start is not None:
        start_index = max(start_index, _first_index_on_or_after(common_dates, evaluation_start))
    end_index = len(common_dates) - 1
    if evaluation_end is not None:
        end_index = _last_index_on_or_before(common_dates, evaluation_end)
    if end_index <= start_index:
        raise ValueError("evaluation interval must contain at least two common trading dates")

    equity = 1.0
    cash = 1.0
    shares: dict[str, float] = {}
    one_way_cost = active_config.round_trip_cost_bps / 20_000.0
    equity_curve = [EtfRotationEquityPoint(trade_date=common_dates[start_index - 1], equity=equity)]
    rebalances: list[EtfRotationRebalanceEvent] = []
    selection_counts = {security_id: 0 for security_id in identifiers}
    position_fractions: list[float] = []
    cumulative_turnover = 0.0
    cumulative_transaction_cost = 0.0

    for index in range(start_index, end_index + 1):
        trade_date = common_dates[index]
        is_rebalance = (index - warmup) % active_config.rebalance_interval_bars == 0
        if is_rebalance:
            signal_index = index - 1
            scores = _positive_momentum_scores(
                indexed,
                identifiers,
                common_dates,
                signal_index=signal_index,
                lookback=active_config.formation_lookback_bars,
            )
            selected = tuple(
                security_id for _, security_id in scores[: active_config.max_positions]
            )
            target_fraction = _target_position_fraction(
                indexed,
                selected,
                common_dates,
                signal_index=signal_index,
                config=active_config,
            )
            per_security_weight = target_fraction / len(selected) if selected else 0.0
            target_weights = {security_id: per_security_weight for security_id in selected}
            (
                cash,
                shares,
                trade_weight_changes,
                turnover_fraction,
                transaction_cost_fraction,
                transaction_cost,
            ) = _rebalance_at_open(
                cash=cash,
                shares=shares,
                target_weights=target_weights,
                indexed=indexed,
                trade_date=trade_date,
                one_way_cost=one_way_cost,
            )
            cumulative_turnover += turnover_fraction
            cumulative_transaction_cost += transaction_cost
            if selected:
                for security_id in selected:
                    selection_counts[security_id] += 1
            rebalances.append(
                EtfRotationRebalanceEvent(
                    signal_date=common_dates[signal_index],
                    execution_date=trade_date,
                    selected_security_ids=selected,
                    momentum_scores={security_id: score for score, security_id in scores},
                    target_position_fraction=target_fraction,
                    target_weights=target_weights,
                    trade_weight_changes=trade_weight_changes,
                    turnover_fraction=turnover_fraction,
                    transaction_cost_fraction=transaction_cost_fraction,
                )
            )
        equity = _portfolio_value(
            cash,
            shares,
            indexed,
            trade_date,
            use_open=False,
        )
        position_fractions.append(
            _portfolio_position_fraction(
                equity,
                shares,
                indexed,
                trade_date,
                use_open=False,
            )
        )
        equity_curve.append(EtfRotationEquityPoint(trade_date=trade_date, equity=equity))

    if shares:
        final_market_value = sum(
            quantity * indexed[security_id][common_dates[end_index]].close_price
            for security_id, quantity in shares.items()
        )
        final_transaction_cost = final_market_value * one_way_cost
        final_turnover = final_market_value / equity
        equity -= final_transaction_cost
        cumulative_turnover += final_turnover
        cumulative_transaction_cost += final_transaction_cost
        equity_curve[-1] = equity_curve[-1].model_copy(update={"equity": equity})

    daily_returns = [
        current.equity / previous.equity - 1.0
        for previous, current in zip(equity_curve, equity_curve[1:], strict=False)
    ]
    max_drawdown = _maximum_drawdown(point.equity for point in equity_curve)
    years = max((common_dates[end_index] - common_dates[start_index]).days / 365.25, 1 / 12)
    total_return = equity - 1.0
    benchmark_return = statistics.fmean(
        indexed[security_id][common_dates[end_index]].close_price
        / indexed[security_id][common_dates[start_index]].open_price
        - 1.0
        for security_id in identifiers
    )
    return EtfRotationBacktestResult(
        evaluation_start=common_dates[start_index],
        evaluation_end=common_dates[end_index],
        total_return=total_return,
        annualized_return=equity ** (1.0 / years) - 1.0,
        max_drawdown=max_drawdown,
        sharpe_ratio=_annualized_sharpe(daily_returns),
        equal_weight_benchmark_return=benchmark_return,
        excess_return=total_return - benchmark_return,
        rebalance_count=len(rebalances),
        active_rebalance_count=sum(bool(event.selected_security_ids) for event in rebalances),
        average_position_fraction=(
            statistics.fmean(position_fractions) if position_fractions else 0.0
        ),
        cumulative_turnover=cumulative_turnover,
        average_rebalance_turnover=(
            statistics.fmean(event.turnover_fraction for event in rebalances) if rebalances else 0.0
        ),
        cumulative_transaction_cost=cumulative_transaction_cost,
        round_trip_cost_bps=active_config.round_trip_cost_bps,
        selection_counts={key: value for key, value in selection_counts.items() if value},
        equity_curve=tuple(equity_curve),
        rebalances=tuple(rebalances),
    )


def validate_etf_rotation_strategy(
    bars_by_security: Mapping[str, Sequence[Bar]],
    *,
    security_ids: Sequence[str],
    config: EtfRotationBacktestConfig | None = None,
    evaluation_start: date | None = None,
    evaluation_end: date | None = None,
) -> EtfRotationValidationReport:
    active_config = config or EtfRotationBacktestConfig()
    base = run_etf_rotation_backtest(
        bars_by_security,
        security_ids=security_ids,
        config=active_config,
        evaluation_start=evaluation_start,
        evaluation_end=evaluation_end,
    )
    stress = run_etf_rotation_backtest(
        bars_by_security,
        security_ids=security_ids,
        config=active_config.model_copy(
            update={"round_trip_cost_bps": active_config.stress_round_trip_cost_bps}
        ),
        evaluation_start=evaluation_start,
        evaluation_end=evaluation_end,
    )
    folds = walk_forward_validate_etf_rotation(
        bars_by_security,
        security_ids=security_ids,
        config=active_config,
        evaluation_start=evaluation_start,
        evaluation_end=evaluation_end,
    )
    positive_ratio = sum(fold.total_return > 0 for fold in folds) / len(folds) if folds else 0.0
    excess_ratio = sum(fold.excess_return > 0 for fold in folds) / len(folds) if folds else 0.0
    base_pass = (
        base.total_return > 0
        and base.excess_return > 0
        and base.max_drawdown >= -active_config.maximum_acceptable_drawdown
        and base.sharpe_ratio >= active_config.minimum_sharpe_ratio
    )
    stress_pass = stress.total_return > 0
    rolling_pass = (
        len(folds) >= active_config.minimum_walk_forward_folds
        and positive_ratio >= active_config.minimum_walk_forward_positive_ratio
        and excess_ratio >= active_config.minimum_walk_forward_excess_ratio
    )
    status = EtfRotationValidationStatus.FAIL
    if base_pass and stress_pass and rolling_pass:
        status = EtfRotationValidationStatus.PASS
    elif base.total_return > 0 and stress_pass:
        status = EtfRotationValidationStatus.WATCH
    notes = (
        f"base_pass={base_pass}",
        f"stress_pass={stress_pass}",
        f"rolling_pass={rolling_pass}",
        f"walk_forward_folds={len(folds)}/{active_config.minimum_walk_forward_folds}",
        "research_only_no_live_order_path",
    )
    return EtfRotationValidationReport(
        status=status,
        config=active_config,
        base=base,
        stress=stress,
        walk_forward_folds=folds,
        walk_forward_positive_ratio=positive_ratio,
        walk_forward_excess_ratio=excess_ratio,
        notes=notes,
    )


def walk_forward_validate_etf_rotation(
    bars_by_security: Mapping[str, Sequence[Bar]],
    *,
    security_ids: Sequence[str],
    config: EtfRotationBacktestConfig,
    evaluation_start: date | None = None,
    evaluation_end: date | None = None,
) -> tuple[EtfRotationWalkForwardFold, ...]:
    identifiers = tuple(dict.fromkeys(security_ids))
    common_dates = sorted(
        set.intersection(
            *(
                {bar.trade_date for bar in bars_by_security[security_id]}
                for security_id in identifiers
            )
        )
    )
    warmup = max(config.formation_lookback_bars, config.volatility_lookback_bars) + 1
    first_index = warmup
    if evaluation_start is not None:
        first_index = max(first_index, _first_index_on_or_after(common_dates, evaluation_start))
    last_index = len(common_dates) - 1
    if evaluation_end is not None:
        last_index = _last_index_on_or_before(common_dates, evaluation_end)
    folds: list[EtfRotationWalkForwardFold] = []
    fold_start = first_index
    fold_number = 1
    while fold_start + config.walk_forward_window_bars - 1 <= last_index:
        fold_end = fold_start + config.walk_forward_window_bars - 1
        result = run_etf_rotation_backtest(
            bars_by_security,
            security_ids=identifiers,
            config=config,
            evaluation_start=common_dates[fold_start],
            evaluation_end=common_dates[fold_end],
        )
        folds.append(
            EtfRotationWalkForwardFold(
                fold_id=f"fold-{fold_number}",
                evaluation_start=result.evaluation_start,
                evaluation_end=result.evaluation_end,
                total_return=result.total_return,
                excess_return=result.excess_return,
                max_drawdown=result.max_drawdown,
                sharpe_ratio=result.sharpe_ratio,
            )
        )
        fold_number += 1
        fold_start += config.walk_forward_step_bars
    return tuple(folds)


def _positive_momentum_scores(
    indexed: Mapping[str, Mapping[date, Bar]],
    identifiers: Sequence[str],
    dates: Sequence[date],
    *,
    signal_index: int,
    lookback: int,
) -> list[tuple[float, str]]:
    scores = []
    for security_id in identifiers:
        score = (
            indexed[security_id][dates[signal_index]].close_price
            / indexed[security_id][dates[signal_index - lookback]].close_price
            - 1.0
        )
        if score > 0:
            scores.append((score, security_id))
    scores.sort(reverse=True)
    return scores


def _target_position_fraction(
    indexed: Mapping[str, Mapping[date, Bar]],
    selected: Sequence[str],
    dates: Sequence[date],
    *,
    signal_index: int,
    config: EtfRotationBacktestConfig,
) -> float:
    if not selected:
        return 0.0
    annual_volatilities = []
    start_index = signal_index - config.volatility_lookback_bars
    for security_id in selected:
        closes = [
            indexed[security_id][dates[index]].close_price
            for index in range(start_index, signal_index + 1)
        ]
        returns = [
            current / previous - 1.0 for previous, current in zip(closes, closes[1:], strict=False)
        ]
        annual_volatilities.append(statistics.pstdev(returns) * math.sqrt(252))
    average_volatility = max(statistics.fmean(annual_volatilities), 0.05)
    return min(
        config.max_position_fraction,
        max(config.min_position_fraction, config.target_annual_volatility / average_volatility),
    )


def _rebalance_at_open(
    *,
    cash: float,
    shares: Mapping[str, float],
    target_weights: Mapping[str, float],
    indexed: Mapping[str, Mapping[date, Bar]],
    trade_date: date,
    one_way_cost: float,
) -> tuple[float, dict[str, float], dict[str, float], float, float, float]:
    current_notionals = {
        security_id: quantity * indexed[security_id][trade_date].open_price
        for security_id, quantity in shares.items()
    }
    equity_before_cost = cash + sum(current_notionals.values())
    if equity_before_cost <= 0:
        raise ValueError("portfolio equity must remain positive before rebalance")

    equity_after_cost = equity_before_cost
    target_notionals: dict[str, float] = {}
    transaction_cost = 0.0
    for _ in range(32):
        target_notionals = {
            security_id: equity_after_cost * weight
            for security_id, weight in target_weights.items()
        }
        traded_notional = sum(
            abs(target_notionals.get(security_id, 0.0) - current_notionals.get(security_id, 0.0))
            for security_id in set(current_notionals) | set(target_notionals)
        )
        transaction_cost = one_way_cost * traded_notional
        updated_equity = equity_before_cost - transaction_cost
        if updated_equity <= 0:
            raise ValueError("transaction costs exhausted portfolio equity")
        if math.isclose(updated_equity, equity_after_cost, rel_tol=0, abs_tol=1e-14):
            equity_after_cost = updated_equity
            break
        equity_after_cost = updated_equity
    target_notionals = {
        security_id: equity_after_cost * weight for security_id, weight in target_weights.items()
    }
    trade_weight_changes = {
        security_id: (
            target_notionals.get(security_id, 0.0) - current_notionals.get(security_id, 0.0)
        )
        / equity_before_cost
        for security_id in set(current_notionals) | set(target_notionals)
        if not math.isclose(
            target_notionals.get(security_id, 0.0),
            current_notionals.get(security_id, 0.0),
            rel_tol=0,
            abs_tol=1e-14,
        )
    }
    turnover_fraction = sum(abs(value) for value in trade_weight_changes.values())
    new_shares = {
        security_id: notional / indexed[security_id][trade_date].open_price
        for security_id, notional in target_notionals.items()
        if notional > 0
    }
    new_cash = equity_after_cost - sum(target_notionals.values())
    return (
        max(new_cash, 0.0),
        new_shares,
        trade_weight_changes,
        turnover_fraction,
        transaction_cost / equity_before_cost,
        transaction_cost,
    )


def _portfolio_value(
    cash: float,
    shares: Mapping[str, float],
    indexed: Mapping[str, Mapping[date, Bar]],
    trade_date: date,
    *,
    use_open: bool,
) -> float:
    return cash + sum(
        quantity
        * (
            indexed[security_id][trade_date].open_price
            if use_open
            else indexed[security_id][trade_date].close_price
        )
        for security_id, quantity in shares.items()
    )


def _portfolio_position_fraction(
    equity: float,
    shares: Mapping[str, float],
    indexed: Mapping[str, Mapping[date, Bar]],
    trade_date: date,
    *,
    use_open: bool,
) -> float:
    if equity <= 0:
        return 0.0
    market_value = sum(
        quantity
        * (
            indexed[security_id][trade_date].open_price
            if use_open
            else indexed[security_id][trade_date].close_price
        )
        for security_id, quantity in shares.items()
    )
    return min(1.0, max(0.0, market_value / equity))


def _maximum_drawdown(values: Iterable[float]) -> float:
    peak = 0.0
    drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            drawdown = min(drawdown, value / peak - 1.0)
    return drawdown


def _annualized_sharpe(returns: Sequence[float]) -> float:
    if not returns:
        return 0.0
    standard_deviation = statistics.pstdev(returns)
    if standard_deviation <= 0:
        return 0.0
    return statistics.fmean(returns) / standard_deviation * math.sqrt(252)


def _first_index_on_or_after(dates: Sequence[date], target: date) -> int:
    for index, current in enumerate(dates):
        if current >= target:
            return index
    raise ValueError(f"evaluation_start {target.isoformat()} is after available history")


def _last_index_on_or_before(dates: Sequence[date], target: date) -> int:
    for index in range(len(dates) - 1, -1, -1):
        if dates[index] <= target:
            return index
    raise ValueError(f"evaluation_end {target.isoformat()} is before available history")
