"""Profit validation strategy tests for TASK-027 core evidence."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from china_quant_platform.domain import (
    AdjustmentMode,
    Bar,
    BarInterval,
    RecordQualityStatus,
)
from china_quant_platform.strategies import (
    HorizonPreset,
    ProfitSeekingConfig,
    ProfitValidationStatus,
    default_etf_validation_universe,
    default_mixed_validation_universe,
    horizon_parameters,
    profit_strategy_config,
    profitability_evidence_from_validation,
    run_profit_strategy_backtest,
    run_profit_validation_lab,
    select_profit_threshold,
)
from china_quant_platform.strategies.lab import report_summary
from china_quant_platform.ui import BacktestPanelState


def make_daily_bars(
    security_id: str = "SSE:513300",
    *,
    count: int = 900,
    start: date = date(2022, 1, 3),
    regime: str = "cyclical_up",
) -> tuple[Bar, ...]:
    bars: list[Bar] = []
    current_day = start
    trading_index = 0
    close = 1.0
    previous_close = close
    while len(bars) < count:
        if current_day.weekday() >= 5:
            current_day += timedelta(days=1)
            continue
        daily_return = _daily_return(trading_index, regime)
        open_price = max(previous_close * (1.0 + daily_return * 0.25), 0.01)
        close = max(previous_close * (1.0 + daily_return), 0.01)
        high = max(open_price, close) * 1.01
        low = min(open_price, close) * 0.99
        start_time = datetime.combine(current_day, time(9, 30), tzinfo=UTC)
        end_time = datetime.combine(current_day, time(15, 0), tzinfo=UTC)
        bars.append(
            Bar(
                security_id=security_id,
                interval=BarInterval.DAILY,
                start_time=start_time,
                end_time=end_time,
                trade_date=current_day,
                open_price=open_price,
                high_price=high,
                low_price=low,
                close_price=close,
                volume=1_000_000 + trading_index * 100,
                amount=close * (1_000_000 + trading_index * 100),
                adjustment=AdjustmentMode.NONE,
                provider="fixture",
                schema_version="fixture.v1",
                source_time=end_time,
                observed_at=end_time,
                received_at=end_time + timedelta(seconds=1),
                quality_status=RecordQualityStatus.OK,
            )
        )
        previous_close = close
        trading_index += 1
        current_day += timedelta(days=1)
    return tuple(bars)


def _daily_return(index: int, regime: str) -> float:
    if regime == "down":
        return -0.0015 if index > 80 else 0.0002
    if regime == "late_crash":
        return -0.012 if index >= 700 else _daily_return(index, "cyclical_up")
    if regime == "late_rally":
        return 0.006 if index >= 700 else _daily_return(index, "cyclical_up")
    cycle = index % 120
    if cycle < 72:
        return 0.0025
    if cycle < 96:
        return -0.004
    return 0.0006


def test_horizon_presets_define_distinct_holding_periods() -> None:
    assert horizon_parameters(HorizonPreset.ONE_MONTH).holding_days == 21
    assert horizon_parameters(HorizonPreset.THREE_MONTHS).holding_days == 63
    assert horizon_parameters(HorizonPreset.SIX_MONTHS).long_lookback == 252
    assert horizon_parameters(HorizonPreset.ONE_YEAR).warmup_bars > 252


def test_canonical_short_and_long_configs_are_distinct() -> None:
    short = profit_strategy_config("short_term", HorizonPreset.ONE_MONTH, 12)
    long = profit_strategy_config("long_term", HorizonPreset.SIX_MONTHS, 4)

    assert short.strategy_version == "profit-validation-short-v2"
    assert long.strategy_version == "profit-validation-long-v2"
    assert short.max_annual_volatility > long.max_annual_volatility
    assert short.minimum_validation_bars < long.minimum_validation_bars
    assert short.minimum_trend_efficiency == 0.10


def test_profit_strategy_respects_annual_trade_limit_and_outputs_risk_metrics() -> None:
    config = ProfitSeekingConfig(
        horizon=HorizonPreset.ONE_MONTH,
        max_trades_per_year=4,
        minimum_oos_bars=80,
        minimum_validation_bars=80,
        minimum_trades_for_pass=1,
    )

    result = run_profit_strategy_backtest(
        "SSE:513300",
        make_daily_bars(),
        config=config,
        include_walk_forward=True,
    )

    assert result.trade_count > 0
    assert all(count <= config.max_trades_per_year for count in result.trades_per_year.values())
    assert result.total_return > -0.20
    assert result.max_drawdown <= 0
    assert result.benchmark_max_drawdown <= 0
    assert result.annualized_volatility >= 0
    assert result.sharpe_ratio is not None
    assert result.calmar_ratio is not None
    assert result.win_rate >= 0
    assert result.calibration_sample_count == result.trade_count
    assert result.brier_score is not None
    assert result.reliability_grade.value in {"A", "B", "C", "N"}
    assert result.walk_forward_active_folds > 0
    assert result.walk_forward_positive_ratio is not None
    assert result.walk_forward_median_return is not None
    assert "不代表保证未来收益" in " ".join(result.notes)


def test_threshold_selection_does_not_use_final_oos_tail() -> None:
    prefix = make_daily_bars(count=700)
    crash_tail = make_daily_bars(
        count=200,
        start=prefix[-1].trade_date + timedelta(days=1),
        regime="late_crash",
    )
    rally_tail = make_daily_bars(
        count=200,
        start=prefix[-1].trade_date + timedelta(days=1),
        regime="late_rally",
    )
    crash_bars = _relabel_and_continue("SSE:513300", prefix, crash_tail)
    rally_bars = _relabel_and_continue("SSE:513300", prefix, rally_tail)
    config = ProfitSeekingConfig(
        horizon=HorizonPreset.ONE_MONTH,
        max_trades_per_year=8,
        minimum_oos_bars=80,
        minimum_validation_bars=80,
    )

    crash_selection = select_profit_threshold(
        "SSE:513300",
        crash_bars,
        config=config,
        final_start_index=650,
    )
    rally_selection = select_profit_threshold(
        "SSE:513300",
        rally_bars,
        config=config,
        final_start_index=650,
    )

    assert crash_selection.selected_threshold == rally_selection.selected_threshold
    assert crash_selection.candidates == rally_selection.candidates


def test_default_etf_validation_lab_builds_aggregate_profitability_evidence() -> None:
    universe = default_etf_validation_universe()
    assert len(universe) == 10
    assert any(member.security_id == "SSE:513300" for member in universe)
    bars_by_security = {
        member.security_id: make_daily_bars(member.security_id, count=900) for member in universe
    }
    config = ProfitSeekingConfig(
        horizon=HorizonPreset.ONE_MONTH,
        max_trades_per_year=6,
        minimum_oos_bars=80,
        minimum_validation_bars=80,
        minimum_trades_for_pass=1,
    )

    report = run_profit_validation_lab(bars_by_security, config=config)
    evidence = profitability_evidence_from_validation(report)
    single_evidence = profitability_evidence_from_validation(report, security_id="SSE:513300")

    assert report.aggregate.security_count == 10
    assert report.aggregate.total_trade_count > 0
    assert report.aggregate.status in {
        ProfitValidationStatus.PASS,
        ProfitValidationStatus.WATCH,
        ProfitValidationStatus.FAIL,
    }
    assert report.results[0].walk_forward
    assert evidence.source == "profit_validation_lab"
    assert evidence.trade_count == report.aggregate.total_trade_count
    assert evidence.checksum == report.checksum
    assert single_evidence.source == "profit_validation_oos"
    assert single_evidence.trade_count == report.results[1].trade_count
    assert single_evidence.sharpe_ratio == report.results[1].sharpe_ratio
    assert single_evidence.benchmark_max_drawdown == report.results[1].benchmark_max_drawdown
    assert (
        single_evidence.walk_forward_positive_ratio == report.results[1].walk_forward_positive_ratio
    )
    summary = report_summary(report, provider_id="fixture")
    assert summary["provider"] == "fixture"
    summary_results = summary["results"]
    assert isinstance(summary_results, list)
    assert len(summary_results) == 10
    assert summary_results[0]["walk_forward_positive_ratio"] is not None


def test_mixed_validation_universe_covers_stocks_and_etfs() -> None:
    universe = default_mixed_validation_universe()

    assert len(universe) == 10
    assert sum(member.asset_type.value == "STOCK" for member in universe) == 5
    assert sum(member.asset_type.value == "ETF" for member in universe) == 5
    assert {member.security_id for member in universe} >= {
        "SSE:600519",
        "SSE:513300",
    }


def test_downtrend_does_not_pass_profit_validation() -> None:
    config = ProfitSeekingConfig(
        horizon=HorizonPreset.ONE_MONTH,
        max_trades_per_year=8,
        minimum_oos_bars=80,
        minimum_validation_bars=80,
        minimum_trades_for_pass=1,
    )

    result = run_profit_strategy_backtest(
        "SSE:513300",
        make_daily_bars(regime="down"),
        config=config,
    )

    assert result.status is not ProfitValidationStatus.PASS
    assert result.trade_count == 0 or result.total_return <= 0


def test_volume_confirmation_filter_blocks_unconfirmed_entries() -> None:
    base_config = ProfitSeekingConfig(
        horizon=HorizonPreset.ONE_MONTH,
        max_trades_per_year=8,
        minimum_oos_bars=80,
        minimum_validation_bars=80,
        minimum_trades_for_pass=1,
    )
    strict_volume_config = base_config.model_copy(update={"min_volume_confirmation": 1.20})
    bars = make_daily_bars()

    baseline = run_profit_strategy_backtest("SSE:513300", bars, config=base_config)
    strict_volume = run_profit_strategy_backtest(
        "SSE:513300",
        bars,
        config=strict_volume_config,
    )

    assert baseline.trade_count > 0
    assert strict_volume.trade_count < baseline.trade_count
    assert "成交量确认" in " ".join(strict_volume.notes)


def test_overheated_short_momentum_is_not_chased() -> None:
    base_config = ProfitSeekingConfig(
        horizon=HorizonPreset.ONE_MONTH,
        max_trades_per_year=8,
        minimum_oos_bars=80,
        minimum_validation_bars=80,
        minimum_trades_for_pass=1,
        max_short_momentum_for_entry=1.0,
    )
    guarded_config = base_config.model_copy(update={"max_short_momentum_for_entry": 0.05})
    bars = make_daily_bars(regime="late_rally")

    unguarded = run_profit_strategy_backtest("SSE:513300", bars, config=base_config)
    guarded = run_profit_strategy_backtest("SSE:513300", bars, config=guarded_config)

    assert guarded.trade_count <= unguarded.trade_count
    assert "过热" in " ".join(guarded.notes)


def test_trend_efficiency_filter_is_part_of_entry_evidence() -> None:
    config = ProfitSeekingConfig(
        horizon=HorizonPreset.ONE_MONTH,
        max_trades_per_year=8,
        minimum_oos_bars=80,
        minimum_validation_bars=80,
        minimum_trades_for_pass=1,
        minimum_trend_efficiency=0.10,
    )

    result = run_profit_strategy_backtest("SSE:513300", make_daily_bars(), config=config)

    assert "趋势效率低于10%时不入场" in " ".join(result.notes)


def test_backtest_panel_state_lists_trade_operations() -> None:
    config = ProfitSeekingConfig(
        horizon=HorizonPreset.ONE_MONTH,
        max_trades_per_year=4,
        minimum_oos_bars=80,
        minimum_validation_bars=80,
        minimum_trades_for_pass=1,
    )
    result = run_profit_strategy_backtest(
        "SSE:513300",
        make_daily_bars(),
        config=config,
        include_walk_forward=True,
    )

    panel = BacktestPanelState.from_profit_result(result)

    assert panel.trade_count == str(result.trade_count)
    assert panel.sharpe_ratio != "--"
    assert panel.walk_forward_consistency != "--"
    assert panel.trades
    assert "买入" in panel.trades[0]
    assert "卖出" in panel.trades[0]
    assert "收益" in panel.trades[0]


def _relabel_and_continue(
    security_id: str,
    prefix: tuple[Bar, ...],
    tail: tuple[Bar, ...],
) -> tuple[Bar, ...]:
    last_close = prefix[-1].close_price
    rebased_tail: list[Bar] = []
    current_scale = last_close / tail[0].open_price
    for bar in tail:
        rebased_tail.append(
            bar.model_copy(
                update={
                    "security_id": security_id,
                    "open_price": bar.open_price * current_scale,
                    "high_price": bar.high_price * current_scale,
                    "low_price": bar.low_price * current_scale,
                    "close_price": bar.close_price * current_scale,
                    "amount": bar.amount * current_scale,
                }
            )
        )
    return prefix + tuple(rebased_tail)
