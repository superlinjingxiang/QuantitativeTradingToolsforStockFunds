"""Deterministic backtest reports, metrics, and exports."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import math
from collections.abc import Sequence
from datetime import date

from pydantic import Field

from china_quant_platform.backtest import BacktestEvent, BacktestEventType
from china_quant_platform.domain import BacktestConfig
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import NonEmptyString


class EquityPoint(DomainModel):
    day: date
    net_asset_value: float = Field(gt=0)
    benchmark_value: float | None = Field(default=None, gt=0)


class PerformanceSummary(DomainModel):
    total_return: float
    annualized_return: float
    volatility: float
    downside_volatility: float
    max_drawdown: float
    sharpe: float | None = None
    sortino: float | None = None
    calmar: float | None = None


class CalibrationSummary(DomainModel):
    sample_count: int = Field(ge=0)
    brier_score: float | None = Field(default=None, ge=0)
    log_loss: float | None = Field(default=None, ge=0)


class CostSummary(DomainModel):
    total_notional: float = Field(ge=0)
    total_fees: float = Field(ge=0)
    slippage_cost: float = Field(ge=0)
    spread_cost: float = Field(ge=0)
    turnover: float = Field(ge=0)


class TradeLedgerRow(DomainModel):
    event_id: NonEmptyString
    timestamp: NonEmptyString
    event_type: BacktestEventType
    security_id: NonEmptyString | None = None
    order_id: NonEmptyString | None = None
    quantity: int | None = None
    filled_quantity: int | None = None
    price: float | None = None
    notional: float | None = None
    total_fees: float | None = None
    reasons: tuple[NonEmptyString, ...] = ()


class RunManifest(DomainModel):
    code_version: NonEmptyString
    strategy_id: NonEmptyString
    strategy_version: NonEmptyString
    data_snapshot_id: NonEmptyString
    rule_version: NonEmptyString
    seed: int
    input_checksum: NonEmptyString
    event_checksum: NonEmptyString


class BacktestReport(DomainModel):
    manifest: RunManifest
    performance: PerformanceSummary
    calibration: CalibrationSummary
    costs: CostSummary
    trades: tuple[TradeLedgerRow, ...]
    checksum: NonEmptyString


class BacktestReportBuilder:
    def build(
        self,
        *,
        config: BacktestConfig,
        equity_curve: Sequence[EquityPoint],
        events: Sequence[BacktestEvent],
        code_version: str,
        event_checksum: str,
        probabilities: Sequence[float] = (),
        outcomes: Sequence[int] = (),
    ) -> BacktestReport:
        performance = calculate_performance(equity_curve)
        costs = summarize_costs(events, equity_curve)
        calibration = calculate_calibration(probabilities, outcomes)
        trades = trade_ledger(events)
        input_checksum = stable_report_checksum(
            {
                "config": config.to_contract_dict(),
                "equity_curve": [point.to_contract_dict() for point in equity_curve],
            }
        )
        manifest = RunManifest(
            code_version=code_version,
            strategy_id=config.strategy_id,
            strategy_version=config.strategy_version,
            data_snapshot_id=config.data_snapshot_id,
            rule_version=config.rule_version,
            seed=config.seed,
            input_checksum=input_checksum,
            event_checksum=event_checksum,
        )
        report_without_checksum = {
            "manifest": manifest.to_contract_dict(),
            "performance": performance.to_contract_dict(),
            "calibration": calibration.to_contract_dict(),
            "costs": costs.to_contract_dict(),
            "trades": [row.to_contract_dict() for row in trades],
        }
        checksum = stable_report_checksum(report_without_checksum)
        return BacktestReport(
            manifest=manifest,
            performance=performance,
            calibration=calibration,
            costs=costs,
            trades=trades,
            checksum=checksum,
        )


def calculate_performance(equity_curve: Sequence[EquityPoint]) -> PerformanceSummary:
    if len(equity_curve) < 2:
        raise ValueError("equity_curve must contain at least two points")
    values = [point.net_asset_value for point in equity_curve]
    period_returns = [
        current / previous - 1.0 for previous, current in zip(values, values[1:], strict=False)
    ]
    total_return = values[-1] / values[0] - 1.0
    annualized_return = (1.0 + total_return) ** (252.0 / max(len(period_returns), 1)) - 1.0
    volatility = _population_std(period_returns) * math.sqrt(252.0)
    downside = [min(value, 0.0) for value in period_returns]
    downside_volatility = _population_std(downside) * math.sqrt(252.0)
    max_drawdown = _max_drawdown(values)
    average_return = sum(period_returns) / len(period_returns)
    sharpe = (
        None
        if volatility == 0
        else average_return / _population_std(period_returns) * math.sqrt(252.0)
    )
    sortino = (
        None
        if downside_volatility == 0
        else average_return / _population_std(downside) * math.sqrt(252.0)
    )
    calmar = None if max_drawdown == 0 else annualized_return / abs(max_drawdown)
    return PerformanceSummary(
        total_return=total_return,
        annualized_return=annualized_return,
        volatility=volatility,
        downside_volatility=downside_volatility,
        max_drawdown=max_drawdown,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
    )


def calculate_calibration(
    probabilities: Sequence[float],
    outcomes: Sequence[int],
) -> CalibrationSummary:
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must have the same length")
    if not probabilities:
        return CalibrationSummary(sample_count=0)

    clipped = [min(max(probability, 1e-12), 1.0 - 1e-12) for probability in probabilities]
    brier = sum(
        (probability - outcome) ** 2 for probability, outcome in zip(clipped, outcomes, strict=True)
    ) / len(clipped)
    log_loss = -sum(
        outcome * math.log(probability) + (1 - outcome) * math.log(1.0 - probability)
        for probability, outcome in zip(clipped, outcomes, strict=True)
    ) / len(clipped)
    return CalibrationSummary(
        sample_count=len(clipped),
        brier_score=brier,
        log_loss=log_loss,
    )


def summarize_costs(
    events: Sequence[BacktestEvent],
    equity_curve: Sequence[EquityPoint],
) -> CostSummary:
    total_notional = sum(event.notional or 0.0 for event in events)
    total_fees = sum(event.total_fees or 0.0 for event in events)
    slippage_cost = sum(event.slippage_cost or 0.0 for event in events)
    spread_cost = sum(event.spread_cost or 0.0 for event in events)
    average_nav = sum(point.net_asset_value for point in equity_curve) / len(equity_curve)
    turnover = 0.0 if average_nav == 0 else total_notional / average_nav
    return CostSummary(
        total_notional=total_notional,
        total_fees=total_fees,
        slippage_cost=slippage_cost,
        spread_cost=spread_cost,
        turnover=turnover,
    )


def trade_ledger(events: Sequence[BacktestEvent]) -> tuple[TradeLedgerRow, ...]:
    ledger_events = [
        event
        for event in events
        if event.event_type
        in {BacktestEventType.FILL, BacktestEventType.PARTIAL_FILL, BacktestEventType.REJECT}
    ]
    return tuple(
        TradeLedgerRow(
            event_id=event.event_id,
            timestamp=event.timestamp.isoformat(),
            event_type=event.event_type,
            security_id=event.security_id,
            order_id=event.order_id,
            quantity=event.quantity,
            filled_quantity=event.filled_quantity,
            price=event.price,
            notional=event.notional,
            total_fees=event.total_fees,
            reasons=event.reasons,
        )
        for event in ledger_events
    )


def export_trades_csv(report: BacktestReport) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "event_id",
            "timestamp",
            "event_type",
            "security_id",
            "order_id",
            "quantity",
            "filled_quantity",
            "price",
            "notional",
            "total_fees",
            "reasons",
        ]
    )
    for row in report.trades:
        writer.writerow(
            [
                row.event_id,
                row.timestamp,
                row.event_type.value,
                row.security_id or "",
                row.order_id or "",
                row.quantity if row.quantity is not None else "",
                row.filled_quantity if row.filled_quantity is not None else "",
                row.price if row.price is not None else "",
                row.notional if row.notional is not None else "",
                row.total_fees if row.total_fees is not None else "",
                ";".join(row.reasons),
            ]
        )
    return output.getvalue()


def export_html_report(report: BacktestReport) -> str:
    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(row.event_id)}</td>"
        f"<td>{html.escape(row.event_type.value)}</td>"
        f"<td>{_format_optional_float(row.notional)}</td>"
        f"<td>{_format_optional_float(row.total_fees)}</td>"
        "</tr>"
        for row in report.trades
    )
    return (
        '<!doctype html><html><head><meta charset="utf-8"><title>Backtest Report</title></head>'
        "<body>"
        "<h1>"
        f"{html.escape(report.manifest.strategy_id)} "
        f"{html.escape(report.manifest.strategy_version)}"
        "</h1>"
        f"<p>Checksum: {html.escape(report.checksum)}</p>"
        f"<p>Total return: {report.performance.total_return:.6f}</p>"
        f"<p>Max drawdown: {report.performance.max_drawdown:.6f}</p>"
        "<table><thead><tr><th>Event</th><th>Type</th><th>Notional</th><th>Fees</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        "</body></html>"
    )


def stable_report_checksum(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _population_std(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _max_drawdown(values: Sequence[float]) -> float:
    peak = values[0]
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = value / peak - 1.0
        max_drawdown = min(max_drawdown, drawdown)
    return max_drawdown


def _format_optional_float(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"
