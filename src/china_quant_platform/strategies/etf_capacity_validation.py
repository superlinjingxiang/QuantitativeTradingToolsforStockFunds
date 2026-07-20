"""Point-in-time liquidity capacity and impact-cost audit for ETF rotation."""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from datetime import date
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from china_quant_platform.domain import Bar
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import NonEmptyString
from china_quant_platform.strategies.etf_rotation_validation import (
    EtfRotationRebalanceEvent,
)


class EtfTradingSystem(StrEnum):
    T_PLUS_ZERO = "T+0"
    T_PLUS_ONE = "T+1"
    UNKNOWN = "UNKNOWN"


class EtfCapacityStatus(StrEnum):
    PASS = "PASS"
    WATCH = "WATCH"
    FAIL = "FAIL"
    MISSING = "MISSING"


class EtfCapacityAuditConfig(DomainModel):
    """Conservative, configurable execution-capacity assumptions.

    The impact coefficient is a research assumption rather than an exchange
    quote. The square-root term is applied to ADV participation and compared
    with the already established 45bp stress budget.
    """

    model_version: NonEmptyString = "etf-capacity-impact-v1"
    adv_lookback_bars: int = Field(default=20, ge=5)
    target_participation_rate: float = Field(default=0.02, gt=0, le=1)
    maximum_participation_rate: float = Field(default=0.05, gt=0, le=1)
    base_round_trip_cost_bps: float = Field(default=15.0, ge=0)
    square_root_impact_coefficient_bps: float = Field(default=120.0, ge=0)
    stress_round_trip_cost_budget_bps: float = Field(default=45.0, gt=0)
    reference_portfolio_capital: float = Field(default=1_000_000.0, gt=0)
    capital_scenarios: tuple[float, ...] = (
        10_000.0,
        100_000.0,
        1_000_000.0,
        10_000_000.0,
        50_000_000.0,
    )

    @model_validator(mode="after")
    def validate_capacity_ranges(self) -> Self:
        if self.target_participation_rate > self.maximum_participation_rate:
            raise ValueError("target participation must not exceed maximum participation")
        if self.base_round_trip_cost_bps > self.stress_round_trip_cost_budget_bps:
            raise ValueError("base cost must not exceed the stress cost budget")
        if not self.capital_scenarios or any(value <= 0 for value in self.capital_scenarios):
            raise ValueError("capital scenarios must contain positive values")
        if tuple(sorted(set(self.capital_scenarios))) != self.capital_scenarios:
            raise ValueError("capital scenarios must be unique and ascending")
        return self


class EtfCapacityObservation(DomainModel):
    signal_date: date
    execution_date: date
    security_id: NonEmptyString
    order_side: NonEmptyString
    target_weight_change: float = Field(gt=0, le=1)
    portfolio_capital: float = Field(gt=0)
    requested_notional: float = Field(gt=0)
    adv_amount: float | None = Field(default=None, gt=0)
    participation_rate: float | None = Field(default=None, ge=0)
    modeled_round_trip_cost_bps: float | None = Field(default=None, ge=0)
    trading_system: EtfTradingSystem
    missing_reason: str | None = None

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        metrics = (
            self.adv_amount,
            self.participation_rate,
            self.modeled_round_trip_cost_bps,
        )
        if self.missing_reason is None and any(value is None for value in metrics):
            raise ValueError("complete capacity observations require ADV, participation, and cost")
        if self.missing_reason is not None and any(value is not None for value in metrics):
            raise ValueError("missing capacity observations must not contain modeled metrics")
        return self


class EtfCapacityScenarioResult(DomainModel):
    portfolio_capital: float = Field(gt=0)
    status: EtfCapacityStatus
    observation_count: int = Field(ge=0)
    missing_observation_count: int = Field(ge=0)
    max_participation_rate: float | None = Field(default=None, ge=0)
    p95_participation_rate: float | None = Field(default=None, ge=0)
    max_modeled_round_trip_cost_bps: float | None = Field(default=None, ge=0)
    p95_modeled_round_trip_cost_bps: float | None = Field(default=None, ge=0)
    reasons: tuple[NonEmptyString, ...]


class EtfCapacityAuditReport(DomainModel):
    config: EtfCapacityAuditConfig
    as_of_date: date
    reference_scenario: EtfCapacityScenarioResult
    scenarios: tuple[EtfCapacityScenarioResult, ...]
    observations: tuple[EtfCapacityObservation, ...]
    maximum_supported_capital: float | None = Field(default=None, ge=0)
    hard_maximum_supported_capital: float | None = Field(default=None, ge=0)
    trading_systems: dict[str, EtfTradingSystem]
    notes: tuple[NonEmptyString, ...]


def classify_etf_trading_system(
    security_id: str,
    *,
    asset_bucket: str | None = None,
) -> EtfTradingSystem:
    """Return a conservative settlement classification for exchange-traded ETFs."""

    exchange, _, symbol = security_id.partition(":")
    if exchange not in {"SSE", "SZSE"} or not symbol:
        return EtfTradingSystem.UNKNOWN
    normalized_bucket = str(asset_bucket or "").strip().lower()
    t0_buckets = {
        "overseas_equity",
        "bond",
        "gold",
        "commodity",
        "海外etf",
        "债券etf",
        "商品etf",
    }
    if symbol.startswith(("511", "513", "518")) or normalized_bucket in t0_buckets:
        return EtfTradingSystem.T_PLUS_ZERO
    return EtfTradingSystem.T_PLUS_ONE


def audit_etf_rotation_capacity(
    bars_by_security: Mapping[str, Sequence[Bar]],
    *,
    rebalances: Sequence[EtfRotationRebalanceEvent],
    config: EtfCapacityAuditConfig | None = None,
    trading_system_by_security: Mapping[str, EtfTradingSystem | str] | None = None,
) -> EtfCapacityAuditReport:
    """Audit rebalance turnover using only ADV known by each signal date."""

    active_config = config or EtfCapacityAuditConfig()
    trading_systems = {
        security_id: _trading_system_value(
            security_id,
            (trading_system_by_security or {}).get(security_id),
        )
        for security_id in bars_by_security
    }
    sorted_bars = {
        security_id: tuple(sorted(bars, key=lambda item: item.trade_date))
        for security_id, bars in bars_by_security.items()
    }
    previous_weights: dict[str, float] = {}
    observations: list[EtfCapacityObservation] = []
    ordered_rebalances = tuple(
        sorted(rebalances, key=lambda item: (item.signal_date, item.execution_date))
    )

    for event in ordered_rebalances:
        selected = tuple(dict.fromkeys(event.selected_security_ids))
        target_weight = event.target_position_fraction / len(selected) if selected else 0.0
        target_weights = {security_id: target_weight for security_id in selected}
        for security_id in sorted(set(previous_weights) | set(target_weights)):
            weight_change = target_weights.get(security_id, 0.0) - previous_weights.get(
                security_id, 0.0
            )
            if math.isclose(weight_change, 0.0, abs_tol=1e-12):
                continue
            absolute_weight_change = abs(weight_change)
            requested_notional = active_config.reference_portfolio_capital * absolute_weight_change
            adv_amount, missing_reason = _adv_as_of_signal(
                sorted_bars.get(security_id, ()),
                signal_date=event.signal_date,
                lookback=active_config.adv_lookback_bars,
            )
            trading_system = trading_systems.get(
                security_id,
                classify_etf_trading_system(security_id),
            )
            if adv_amount is None:
                observations.append(
                    EtfCapacityObservation(
                        signal_date=event.signal_date,
                        execution_date=event.execution_date,
                        security_id=security_id,
                        order_side="BUY" if weight_change > 0 else "SELL",
                        target_weight_change=absolute_weight_change,
                        portfolio_capital=active_config.reference_portfolio_capital,
                        requested_notional=requested_notional,
                        trading_system=trading_system,
                        missing_reason=missing_reason,
                    )
                )
                continue
            participation = requested_notional / adv_amount
            observations.append(
                EtfCapacityObservation(
                    signal_date=event.signal_date,
                    execution_date=event.execution_date,
                    security_id=security_id,
                    order_side="BUY" if weight_change > 0 else "SELL",
                    target_weight_change=absolute_weight_change,
                    portfolio_capital=active_config.reference_portfolio_capital,
                    requested_notional=requested_notional,
                    adv_amount=adv_amount,
                    participation_rate=participation,
                    modeled_round_trip_cost_bps=_modeled_round_trip_cost_bps(
                        participation,
                        active_config,
                    ),
                    trading_system=trading_system,
                )
            )
        previous_weights = target_weights

    reference = _scenario_from_observations(
        observations,
        portfolio_capital=active_config.reference_portfolio_capital,
        config=active_config,
    )
    scenarios = tuple(
        _scenario_from_observations(
            observations,
            portfolio_capital=capital,
            config=active_config,
        )
        for capital in active_config.capital_scenarios
    )
    participation_scales = [
        observation.participation_rate / active_config.reference_portfolio_capital
        for observation in observations
        if observation.participation_rate is not None
    ]
    maximum_scale = max(participation_scales, default=0.0)
    maximum_supported_capital = (
        active_config.target_participation_rate / maximum_scale if maximum_scale > 0 else None
    )
    hard_maximum_supported_capital = (
        active_config.maximum_participation_rate / maximum_scale if maximum_scale > 0 else None
    )
    as_of_date = (
        max(event.execution_date for event in ordered_rebalances)
        if ordered_rebalances
        else max(
            (bar.trade_date for bars in sorted_bars.values() for bar in bars),
            default=date.today(),
        )
    )
    return EtfCapacityAuditReport(
        config=active_config,
        as_of_date=as_of_date,
        reference_scenario=reference,
        scenarios=scenarios,
        observations=tuple(observations),
        maximum_supported_capital=maximum_supported_capital,
        hard_maximum_supported_capital=hard_maximum_supported_capital,
        trading_systems=trading_systems,
        notes=(
            "adv_uses_signal_date_and_prior_bars_only",
            "turnover_uses_absolute_target_weight_change",
            "impact_is_configured_square_root_model_not_order_book_evidence",
            "paper_fills_still_required_before_execution_upgrade",
        ),
    )


def assess_etf_capacity_scenario(
    report: EtfCapacityAuditReport,
    *,
    portfolio_capital: float,
) -> EtfCapacityScenarioResult:
    """Evaluate an arbitrary account size from normalized reference observations."""

    if portfolio_capital <= 0:
        raise ValueError("portfolio_capital must be positive")
    return _scenario_from_observations(
        report.observations,
        portfolio_capital=portfolio_capital,
        config=report.config,
    )


def _scenario_from_observations(
    observations: Sequence[EtfCapacityObservation],
    *,
    portfolio_capital: float,
    config: EtfCapacityAuditConfig,
) -> EtfCapacityScenarioResult:
    missing_count = sum(observation.missing_reason is not None for observation in observations)
    scale = portfolio_capital / config.reference_portfolio_capital
    participations = [
        observation.participation_rate * scale
        for observation in observations
        if observation.participation_rate is not None
    ]
    costs = [
        _modeled_round_trip_cost_bps(participation, config) for participation in participations
    ]
    reasons: list[str] = []
    if not observations:
        status = EtfCapacityStatus.MISSING
        reasons.append("没有可审计的组合调仓订单。")
    elif missing_count:
        status = EtfCapacityStatus.MISSING
        reasons.append(f"{missing_count}笔调仓缺少信号日前20日有效成交额。")
    else:
        max_participation = max(participations)
        max_cost = max(costs)
        if (
            max_participation <= config.target_participation_rate
            and max_cost <= config.stress_round_trip_cost_budget_bps
        ):
            status = EtfCapacityStatus.PASS
            reasons.append("最大ADV参与率和模型成本均在目标预算内。")
        elif (
            max_participation <= config.maximum_participation_rate
            and max_cost <= config.stress_round_trip_cost_budget_bps
        ):
            status = EtfCapacityStatus.WATCH
            reasons.append("容量高于目标参与率但尚未超过硬上限，需模拟盘成交确认。")
        else:
            status = EtfCapacityStatus.FAIL
            if max_participation > config.maximum_participation_rate:
                reasons.append(
                    f"最大ADV参与率{max_participation:.2%}超过"
                    f"{config.maximum_participation_rate:.2%}硬上限。"
                )
            if max_cost > config.stress_round_trip_cost_budget_bps:
                reasons.append(
                    f"模型往返成本{max_cost:.1f}bp超过"
                    f"{config.stress_round_trip_cost_budget_bps:.1f}bp压力预算。"
                )

    return EtfCapacityScenarioResult(
        portfolio_capital=portfolio_capital,
        status=status,
        observation_count=len(observations),
        missing_observation_count=missing_count,
        max_participation_rate=max(participations) if participations else None,
        p95_participation_rate=_percentile(participations, 0.95),
        max_modeled_round_trip_cost_bps=max(costs) if costs else None,
        p95_modeled_round_trip_cost_bps=_percentile(costs, 0.95),
        reasons=tuple(reasons),
    )


def _adv_as_of_signal(
    bars: Sequence[Bar],
    *,
    signal_date: date,
    lookback: int,
) -> tuple[float | None, str | None]:
    known = [bar for bar in bars if bar.trade_date <= signal_date]
    window = known[-lookback:]
    if len(window) < lookback:
        return None, f"信号日{signal_date.isoformat()}可用成交额不足{lookback}日。"
    if any(bar.amount <= 0 for bar in window):
        return None, f"信号日{signal_date.isoformat()}前{lookback}日存在无效成交额。"
    return statistics.fmean(bar.amount for bar in window), None


def _modeled_round_trip_cost_bps(
    participation_rate: float,
    config: EtfCapacityAuditConfig,
) -> float:
    return config.base_round_trip_cost_bps + config.square_root_impact_coefficient_bps * math.sqrt(
        max(participation_rate, 0.0)
    )


def _trading_system_value(
    security_id: str,
    value: EtfTradingSystem | str | None,
) -> EtfTradingSystem:
    if value is None:
        return classify_etf_trading_system(security_id)
    try:
        return EtfTradingSystem(str(value))
    except ValueError:
        return EtfTradingSystem.UNKNOWN


def _percentile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction
