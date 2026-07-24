"""Standard domain models for securities, market data, rules, and reports."""

from __future__ import annotations

from datetime import date
from math import isclose
from typing import Any, Self

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.enums import (
    AbstainReason,
    AdjustmentMode,
    AssetType,
    BarInterval,
    CorporateActionType,
    Currency,
    DataHealthStatus,
    Exchange,
    FinalSignal,
    FundNavType,
    RecordQualityStatus,
    RuleReviewStatus,
    SecurityStatus,
)
from china_quant_platform.domain.identifiers import (
    DataSnapshotId,
    ModelVersion,
    NonEmptyString,
    ProviderId,
    RuleId,
    RuleVersion,
    SchemaVersion,
    SecurityId,
    StrategyId,
)

TRADEABLE_FINAL_SIGNALS = frozenset(
    {
        FinalSignal.BUY_CANDIDATE,
        FinalSignal.ADD_CANDIDATE,
        FinalSignal.HOLD,
        FinalSignal.REDUCE,
        FinalSignal.SELL,
    }
)


class SourceStampedModel(DomainModel):
    """Base for externally sourced records that retain lineage timestamps."""

    provider: ProviderId
    schema_version: SchemaVersion
    source_time: AwareDatetime
    observed_at: AwareDatetime
    received_at: AwareDatetime
    quality_status: RecordQualityStatus = RecordQualityStatus.OK

    @model_validator(mode="after")
    def received_at_must_not_precede_source_time(self) -> Self:
        if self.received_at < self.source_time:
            raise ValueError("received_at must not be earlier than source_time")
        return self


class SecurityRef(DomainModel):
    security_id: SecurityId
    symbol: NonEmptyString
    name: NonEmptyString
    asset_type: AssetType
    exchange: Exchange
    currency: Currency = Currency.CNY
    listed_date: date
    status_date: date
    status: SecurityStatus
    delisted_date: date | None = None
    aliases: tuple[NonEmptyString, ...] = ()

    @model_validator(mode="after")
    def delisted_date_must_not_precede_listing(self) -> Self:
        if self.delisted_date is not None and self.delisted_date < self.listed_date:
            raise ValueError("delisted_date must not be earlier than listed_date")
        return self


class Quote(SourceStampedModel):
    security_id: SecurityId
    latest_price: float = Field(ge=0)
    previous_close: float = Field(ge=0)
    open_price: float = Field(ge=0)
    high_price: float = Field(ge=0)
    low_price: float = Field(ge=0)
    volume: float = Field(ge=0)
    amount: float = Field(ge=0)
    bid_price: float | None = Field(default=None, ge=0)
    ask_price: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def high_low_must_contain_prices(self) -> Self:
        if self.high_price < max(self.open_price, self.latest_price):
            raise ValueError("high_price must be at least open_price and latest_price")
        if self.low_price > min(self.open_price, self.latest_price):
            raise ValueError("low_price must be at most open_price and latest_price")
        return self


class Bar(SourceStampedModel):
    security_id: SecurityId
    interval: BarInterval
    start_time: AwareDatetime
    end_time: AwareDatetime
    trade_date: date
    open_price: float = Field(ge=0)
    high_price: float = Field(ge=0)
    low_price: float = Field(ge=0)
    close_price: float = Field(ge=0)
    volume: float = Field(ge=0)
    amount: float = Field(ge=0)
    adjustment: AdjustmentMode = AdjustmentMode.NONE

    @model_validator(mode="after")
    def validate_time_window_and_ohlc(self) -> Self:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time")
        if self.high_price < max(self.open_price, self.close_price):
            raise ValueError("high_price must be at least open_price and close_price")
        if self.low_price > min(self.open_price, self.close_price):
            raise ValueError("low_price must be at most open_price and close_price")
        return self


class FundNav(SourceStampedModel):
    fund_id: SecurityId
    nav_date: date
    unit_nav: float = Field(gt=0)
    accumulated_nav: float = Field(gt=0)
    published_at: AwareDatetime
    nav_type: FundNavType = FundNavType.OFFICIAL

    @model_validator(mode="after")
    def official_nav_must_be_official(self) -> Self:
        if self.nav_type is not FundNavType.OFFICIAL:
            raise ValueError("FundNav stores official NAV only; use EstimatedFundNav separately")
        return self


class EstimatedFundNav(SourceStampedModel):
    fund_id: SecurityId
    nav_date: date
    estimated_unit_nav: float = Field(gt=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    nav_type: FundNavType = FundNavType.ESTIMATED

    @model_validator(mode="after")
    def estimated_nav_must_be_estimated(self) -> Self:
        if self.nav_type is not FundNavType.ESTIMATED:
            raise ValueError("EstimatedFundNav cannot be marked as official NAV")
        return self


class CorporateAction(SourceStampedModel):
    security_id: SecurityId
    action_type: CorporateActionType
    announcement_time: AwareDatetime
    ex_date: date | None = None
    record_date: date | None = None
    payment_date: date | None = None
    cash_amount: float | None = Field(default=None, ge=0)
    share_ratio: float | None = Field(default=None, ge=0)


class DataHealth(DomainModel):
    status: DataHealthStatus
    block_signal: bool
    as_of: AwareDatetime
    issues: tuple[str, ...] = ()


class DirectionProbabilities(DomainModel):
    up: float = Field(ge=0, le=1)
    flat: float = Field(ge=0, le=1)
    down: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def probabilities_must_sum_to_one(self) -> Self:
        total = self.up + self.flat + self.down
        if not isclose(total, 1.0, abs_tol=1e-9):
            raise ValueError("direction probabilities must sum to 1")
        return self


class ForecastValidationEvidence(DomainModel):
    sample_count: int = Field(ge=0)
    required_sample_count: int = Field(ge=1)
    candidate_count: int = Field(ge=0)
    evaluation_stride: int = Field(ge=1)
    training_embargo: int = Field(ge=0)
    interval_coverage: float | None = Field(default=None, ge=0, le=1)
    downside_breach_rate: float | None = Field(default=None, ge=0, le=1)
    direction_brier_score: float | None = Field(default=None, ge=0)


class PortfolioStrategyEvidence(DomainModel):
    security_id: SecurityId
    strategy_id: StrategyId
    strategy_version: NonEmptyString
    validation_status: NonEmptyString
    as_of_date: date
    signal_date: date | None = None
    execution_date: date | None = None
    selected_security_ids: tuple[SecurityId, ...] = ()
    current_security_selected: bool = False
    current_security_rank: int | None = Field(default=None, ge=1)
    current_security_momentum: float | None = None
    target_position_fraction: float = Field(default=0.0, ge=0, le=1)
    current_security_target_fraction: float = Field(default=0.0, ge=0, le=1)
    bars_until_next_rebalance: int | None = Field(default=None, ge=1)
    base_total_return: float | None = None
    stress_total_return: float | None = None
    excess_return: float | None = None
    max_drawdown: float | None = Field(default=None, le=0)
    sharpe_ratio: float | None = None
    walk_forward_fold_count: int = Field(default=0, ge=0)
    required_walk_forward_fold_count: int = Field(default=1, ge=1)
    walk_forward_positive_ratio: float | None = Field(default=None, ge=0, le=1)
    walk_forward_excess_ratio: float | None = Field(default=None, ge=0, le=1)
    cumulative_turnover: float | None = Field(default=None, ge=0)
    average_rebalance_turnover: float | None = Field(default=None, ge=0, le=2)
    cumulative_transaction_cost: float | None = Field(default=None, ge=0)
    trading_system: NonEmptyString = "UNKNOWN"
    capacity_status: NonEmptyString = "MISSING"
    capacity_model_version: NonEmptyString = "etf-capacity-impact-v2"
    capacity_reference_capital: float | None = Field(default=None, gt=0)
    capacity_max_participation_rate: float | None = Field(default=None, ge=0)
    capacity_estimated_round_trip_cost_bps: float | None = Field(default=None, ge=0)
    capacity_max_supported_capital: float | None = Field(default=None, ge=0)
    capacity_observation_count: int = Field(default=0, ge=0)
    capacity_missing_observation_count: int = Field(default=0, ge=0)
    stale: bool = False
    failures: tuple[NonEmptyString, ...] = ()
    notes: tuple[NonEmptyString, ...] = ()

    @model_validator(mode="after")
    def enforce_portfolio_evidence_consistency(self) -> Self:
        selected = tuple(dict.fromkeys(self.selected_security_ids))
        if selected != self.selected_security_ids:
            raise ValueError("selected_security_ids must be unique")
        is_selected = self.security_id in selected
        if is_selected != self.current_security_selected:
            raise ValueError("current_security_selected must match selected_security_ids")
        if not is_selected and self.current_security_target_fraction != 0:
            raise ValueError("unselected securities must have zero target fraction")
        if self.current_security_target_fraction > self.target_position_fraction:
            raise ValueError("security target fraction cannot exceed portfolio target fraction")
        if (self.signal_date is None) != (self.execution_date is None):
            raise ValueError("signal_date and execution_date must be provided together")
        capacity_metrics = (
            self.capacity_reference_capital,
            self.capacity_max_participation_rate,
            self.capacity_estimated_round_trip_cost_bps,
            self.capacity_max_supported_capital,
        )
        if self.capacity_status.upper() in {"PASS", "WATCH", "FAIL"}:
            if any(value is None for value in capacity_metrics):
                raise ValueError("audited capacity status requires complete capacity metrics")
            if self.capacity_observation_count <= 0:
                raise ValueError("audited capacity status requires observations")
            if self.capacity_missing_observation_count:
                raise ValueError("audited capacity status cannot contain missing observations")
        return self


class AnalysisReport(DomainModel):
    security_id: SecurityId
    as_of: AwareDatetime
    data_health: DataHealth
    strategy_id: StrategyId
    strategy_version: NonEmptyString
    horizon: int = Field(ge=1)
    strategy_horizon: int | None = Field(default=None, ge=1)
    market_regime: NonEmptyString
    direction_probabilities: DirectionProbabilities
    raw_signal: NonEmptyString
    final_signal: FinalSignal
    valid_until: AwareDatetime
    positive_drivers: tuple[NonEmptyString, ...]
    negative_drivers: tuple[NonEmptyString, ...]
    model_version: ModelVersion
    rule_version: RuleVersion
    data_snapshot_id: DataSnapshotId
    expected_return_quantiles: dict[str, float] = Field(default_factory=dict)
    expected_drawdown: float | None = None
    forecast_validation: ForecastValidationEvidence | None = None
    portfolio_strategy_evidence: PortfolioStrategyEvidence | None = None
    grade: str | None = None
    target_position_limit: float | None = Field(default=None, ge=0, le=1)
    exit_or_invalidation_conditions: tuple[NonEmptyString, ...] = ()
    abstain_reason: AbstainReason | None = None

    @model_validator(mode="after")
    def enforce_report_invariants(self) -> Self:
        if self.valid_until <= self.as_of:
            raise ValueError("valid_until must be later than as_of")

        if self.final_signal is FinalSignal.ABSTAIN and self.abstain_reason is None:
            raise ValueError("ABSTAIN reports must include abstain_reason")

        if self.final_signal in TRADEABLE_FINAL_SIGNALS:
            if self.data_health.block_signal:
                raise ValueError("tradeable reports require data_health.block_signal == false")
            if not self.positive_drivers or not self.negative_drivers:
                raise ValueError("tradeable reports require positive and negative drivers")
            if not self.exit_or_invalidation_conditions:
                raise ValueError("tradeable reports require invalidation or exit conditions")

        return self


class BacktestConfig(DomainModel):
    strategy_id: StrategyId
    strategy_version: NonEmptyString
    start_date: date
    end_date: date
    initial_cash: float = Field(gt=0)
    data_snapshot_id: DataSnapshotId
    rule_version: RuleVersion
    seed: int
    universe_id: str | None = None
    benchmark_id: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def end_date_must_not_precede_start_date(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be earlier than start_date")
        return self


class SecurityRule(DomainModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    rule_id: RuleId
    version: RuleVersion
    exchange: Exchange | NonEmptyString
    asset_type: AssetType | NonEmptyString
    effective_from: date
    source: NonEmptyString
    review_status: RuleReviewStatus
    security_id: SecurityId | None = None
    effective_to: date | None = None
    lot_size: int | None = Field(default=None, ge=1)
    tick_size: float | None = Field(default=None, gt=0)
    intraday_round_trip: bool | None = None

    @model_validator(mode="after")
    def effective_to_must_not_precede_effective_from(self) -> Self:
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must not be earlier than effective_from")
        return self
