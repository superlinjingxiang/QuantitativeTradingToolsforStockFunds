"""Profit validation strategy tests for TASK-027 core evidence."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time, timedelta

import pytest

import china_quant_platform.strategies.profit_validation as profit_validation_module
from china_quant_platform.data import BarsRequest
from china_quant_platform.domain import (
    AdjustmentMode,
    Bar,
    BarInterval,
    RecordQualityStatus,
)
from china_quant_platform.strategies import (
    HorizonPreset,
    ProfitBacktestResult,
    ProfitSeekingConfig,
    ProfitSignalFeatures,
    ProfitValidationStatus,
    default_a_share_confirmation_universe,
    default_a_share_shadow_universe,
    default_a_share_validation_universe,
    default_etf_validation_universe,
    default_mixed_validation_universe,
    horizon_parameters,
    profit_strategy_config,
    profitability_evidence_from_validation,
    run_profit_strategy_backtest,
    run_profit_validation_lab,
    select_profit_threshold,
)
from china_quant_platform.strategies.lab import report_summary, validate_profit_universe
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
    if regime == "volatile_trend":
        return 0.025 if index % 20 < 12 else -0.015
    cycle = index % 120
    if cycle < 72:
        return 0.0025
    if cycle < 96:
        return -0.004
    return 0.0006


def _passing_features(as_of: date = date(2026, 7, 13)) -> ProfitSignalFeatures:
    return ProfitSignalFeatures(
        as_of=as_of,
        score=0.50,
        predicted_probability=0.625,
        one_day_return=0.01,
        short_momentum=0.10,
        long_momentum=0.20,
        trend_strength=0.05,
        trend_efficiency=0.50,
        regime_momentum=0.10,
        regime_trend_strength=0.05,
        annualized_volatility=0.30,
        drawdown=-0.05,
        volume_ratio=1.20,
        liquidity_score=0.80,
    )


def test_horizon_presets_define_distinct_holding_periods() -> None:
    assert horizon_parameters(HorizonPreset.ONE_MONTH).holding_days == 21
    assert horizon_parameters(HorizonPreset.THREE_MONTHS).holding_days == 63
    assert horizon_parameters(HorizonPreset.SIX_MONTHS).long_lookback == 252
    assert horizon_parameters(HorizonPreset.ONE_YEAR).warmup_bars > 252
    assert horizon_parameters(HorizonPreset.ONE_MONTH).regime_lookback == 126


def test_canonical_short_and_long_configs_are_distinct() -> None:
    short = profit_strategy_config("short_term", HorizonPreset.ONE_MONTH, 12)
    long = profit_strategy_config("long_term", HorizonPreset.SIX_MONTHS, 4)

    assert short.strategy_version == "profit-validation-short-v7"
    assert long.strategy_version == "profit-validation-long-v3"
    assert short.max_annual_volatility > long.max_annual_volatility
    assert short.target_annual_volatility == 0.20
    assert long.target_annual_volatility is None
    assert short.stop_loss_pct == 0.075
    assert short.minimum_validation_bars < long.minimum_validation_bars
    assert short.minimum_trend_efficiency == 0.10
    assert short.apply_a_share_anti_chase is True
    assert short.a_share_max_one_day_return_for_entry == 0.03
    assert short.a_share_max_short_momentum_for_entry == 0.15
    assert short.apply_a_share_market_regime_filter is True
    assert short.market_regime_security_id == "SSE:510300"
    assert short.market_regime_short_lookback == 21
    assert short.market_regime_long_lookback == 63
    assert short.execute_close_signals_at_next_open is True
    assert short.apply_a_share_t_plus_one is True
    assert short.block_a_share_one_price_limits is True
    assert long.apply_a_share_anti_chase is False
    assert long.execute_close_signals_at_next_open is False
    assert long.apply_a_share_t_plus_one is False
    assert long.block_a_share_one_price_limits is False


def test_a_share_anti_chase_limit_does_not_change_etf_entries() -> None:
    config = profit_strategy_config("short_term", HorizonPreset.ONE_MONTH, 12)
    features = ProfitSignalFeatures(
        as_of=date(2026, 7, 13),
        score=0.50,
        predicted_probability=0.625,
        one_day_return=0.04,
        short_momentum=0.10,
        long_momentum=0.20,
        trend_strength=0.05,
        trend_efficiency=0.50,
        regime_momentum=0.10,
        regime_trend_strength=0.05,
        annualized_volatility=0.30,
        drawdown=-0.05,
        volume_ratio=1.20,
        liquidity_score=0.80,
    )

    assert not profit_validation_module._entry_signal_passes(
        "SSE:600519",
        features,
        threshold=0.10,
        config=config,
    )
    assert profit_validation_module._entry_signal_passes(
        "SSE:513300",
        features,
        threshold=0.10,
        config=config,
    )


def test_a_share_volume_confirmation_does_not_change_etf_entries() -> None:
    config = profit_strategy_config(
        "short_term",
        HorizonPreset.ONE_MONTH,
        12,
    ).model_copy(update={"a_share_min_volume_confirmation": 1.0})
    features = _passing_features().model_copy(update={"volume_ratio": 0.90})

    assert not profit_validation_module._entry_signal_passes(
        "SSE:600519",
        features,
        threshold=0.10,
        config=config,
    )
    assert profit_validation_module._entry_signal_passes(
        "SSE:513300",
        features,
        threshold=0.10,
        config=config,
    )


def test_a_share_market_regime_gate_is_point_in_time_and_etf_is_unaffected() -> None:
    config = profit_strategy_config("short_term", HorizonPreset.ONE_MONTH, 12)
    rising = tuple(
        bar.model_copy(
            update={
                "open_price": 100.0 + index,
                "high_price": 100.5 + index,
                "low_price": 99.5 + index,
                "close_price": 100.0 + index,
            }
        )
        for index, bar in enumerate(make_daily_bars("SSE:510300", count=100))
    )
    as_of = rising[80].trade_date
    baseline = profit_validation_module._market_regime_evidence(
        security_id="SSE:600519",
        as_of=as_of,
        market_regime_bars=rising,
        config=config,
    )
    future_crash = tuple(
        bar.model_copy(
            update={
                "open_price": bar.open_price * 0.50,
                "high_price": bar.high_price * 0.50,
                "low_price": bar.low_price * 0.50,
                "close_price": bar.close_price * 0.50,
            }
        )
        if index > 80
        else bar
        for index, bar in enumerate(rising)
    )
    with_future_changed = profit_validation_module._market_regime_evidence(
        security_id="SSE:600519",
        as_of=as_of,
        market_regime_bars=future_crash,
        config=config,
    )
    etf = profit_validation_module._market_regime_evidence(
        security_id="SSE:513300",
        as_of=as_of,
        market_regime_bars=(),
        config=config,
    )

    assert baseline.status is profit_validation_module.MarketRegimeGateStatus.PASS
    assert with_future_changed == baseline
    assert etf.status is profit_validation_module.MarketRegimeGateStatus.NOT_APPLICABLE


def test_a_share_market_regime_gate_blocks_falling_or_missing_market(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stock_bars = make_daily_bars("SSE:600519", count=100)
    rising_market = tuple(
        bar.model_copy(
            update={
                "open_price": 100.0 + index,
                "high_price": 100.5 + index,
                "low_price": 99.5 + index,
                "close_price": 100.0 + index,
            }
        )
        for index, bar in enumerate(make_daily_bars("SSE:510300", count=100))
    )
    falling_market = tuple(
        bar.model_copy(
            update={
                "open_price": 200.0 - index,
                "high_price": 200.5 - index,
                "low_price": 199.5 - index,
                "close_price": 200.0 - index,
            }
        )
        for index, bar in enumerate(rising_market)
    )
    config = profit_strategy_config(
        "short_term",
        HorizonPreset.ONE_MONTH,
        252,
    ).model_copy(update={"stop_loss_pct": 0.50})

    def entry_features(index: int, **_kwargs: object) -> ProfitSignalFeatures | None:
        return _passing_features(stock_bars[index].trade_date) if index == 70 else None

    monkeypatch.setattr(profit_validation_module, "_signal_features", entry_features)
    monkeypatch.setattr(profit_validation_module, "_close_signal_reason", lambda **_kwargs: None)

    def simulate(market_bars: tuple[Bar, ...]) -> ProfitBacktestResult:
        return profit_validation_module._simulate_strategy(
            security_id="SSE:600519",
            bars=stock_bars,
            config=config,
            parameters=horizon_parameters(HorizonPreset.ONE_MONTH),
            start_index=1,
            end_index=90,
            threshold=0.10,
            threshold_selection=None,
            market_regime_bars=market_bars,
        )

    allowed = simulate(rising_market)
    blocked = simulate(falling_market)
    missing = simulate(())

    assert allowed.trade_count == 1
    assert allowed.market_regime.status is profit_validation_module.MarketRegimeGateStatus.PASS
    assert blocked.trade_count == 0
    assert blocked.market_regime.status is profit_validation_module.MarketRegimeGateStatus.BLOCKED
    assert blocked.market_regime.rejected_entry_count == 1
    assert missing.trade_count == 0
    assert missing.market_regime.status is profit_validation_module.MarketRegimeGateStatus.MISSING


def test_close_signal_executes_at_next_open_without_same_day_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars = make_daily_bars("SSE:513300", count=8)
    config = ProfitSeekingConfig(
        max_trades_per_year=252,
        execute_close_signals_at_next_open=True,
        stop_loss_pct=0.50,
    )

    def fake_features(index: int, **_kwargs: object) -> ProfitSignalFeatures | None:
        return _passing_features(bars[index].trade_date) if index == 1 else None

    def fake_exit(*, index: int, **_kwargs: object) -> str | None:
        return "score_breakdown" if index == 3 else None

    monkeypatch.setattr(profit_validation_module, "_signal_features", fake_features)
    monkeypatch.setattr(profit_validation_module, "_close_signal_reason", fake_exit)

    result = profit_validation_module._simulate_strategy(
        security_id="SSE:513300",
        bars=bars,
        config=config,
        parameters=horizon_parameters(HorizonPreset.ONE_MONTH),
        start_index=1,
        end_index=6,
        threshold=0.10,
        threshold_selection=None,
    )

    assert result.trade_count == 1
    assert result.trades[0].entry_date == bars[2].trade_date
    assert result.trades[0].exit_date == bars[4].trade_date
    assert result.trades[0].exit_price == bars[4].open_price
    assert result.next_open_exit_count == 1
    assert result.same_day_exit_count == 0


def test_a_share_t_plus_one_defers_entry_day_stop_to_next_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = list(make_daily_bars("SSE:600519", count=8))
    entry_bar = source[2]
    source[2] = entry_bar.model_copy(
        update={
            "low_price": entry_bar.open_price * 0.80,
        }
    )
    bars = tuple(source)
    config = ProfitSeekingConfig(
        max_trades_per_year=252,
        execute_close_signals_at_next_open=True,
        apply_a_share_t_plus_one=True,
        stop_loss_pct=0.05,
    )

    def fake_features(index: int, **_kwargs: object) -> ProfitSignalFeatures | None:
        return _passing_features(bars[index].trade_date) if index == 1 else None

    monkeypatch.setattr(profit_validation_module, "_signal_features", fake_features)
    monkeypatch.setattr(
        profit_validation_module,
        "_close_signal_reason",
        lambda **_kwargs: None,
    )

    result = profit_validation_module._simulate_strategy(
        security_id="SSE:600519",
        bars=bars,
        config=config,
        parameters=horizon_parameters(HorizonPreset.ONE_MONTH),
        start_index=1,
        end_index=6,
        threshold=0.10,
        threshold_selection=None,
    )

    assert result.trade_count == 1
    assert result.trades[0].entry_date == bars[2].trade_date
    assert result.trades[0].exit_date == bars[3].trade_date
    assert result.trades[0].exit_price == bars[3].open_price
    assert result.trades[0].exit_reason == "stop_loss"
    assert result.next_open_exit_count == 1
    assert result.same_day_exit_count == 0
    assert result.t_plus_one_deferral_count == 1


def test_daily_trailing_stop_uses_prior_peak_without_intrabar_lookahead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = list(make_daily_bars("SSE:513300", count=8))
    entry_bar = source[2]
    source[2] = entry_bar.model_copy(
        update={
            "high_price": entry_bar.open_price * 1.10,
            "low_price": entry_bar.open_price * 0.96,
            "close_price": entry_bar.open_price * 1.05,
        }
    )
    next_bar = source[3]
    source[3] = next_bar.model_copy(
        update={
            "open_price": entry_bar.open_price * 1.04,
            "high_price": entry_bar.open_price * 1.05,
            "low_price": entry_bar.open_price,
            "close_price": entry_bar.open_price * 1.02,
        }
    )
    bars = tuple(source)
    config = ProfitSeekingConfig(
        max_trades_per_year=252,
        stop_loss_pct=0.075,
    )

    def fake_features(index: int, **_kwargs: object) -> ProfitSignalFeatures | None:
        return _passing_features(bars[index].trade_date) if index == 1 else None

    monkeypatch.setattr(profit_validation_module, "_signal_features", fake_features)
    monkeypatch.setattr(
        profit_validation_module,
        "_close_signal_reason",
        lambda **_kwargs: None,
    )

    result = profit_validation_module._simulate_strategy(
        security_id="SSE:513300",
        bars=bars,
        config=config,
        parameters=horizon_parameters(HorizonPreset.ONE_MONTH),
        start_index=1,
        end_index=6,
        threshold=0.10,
        threshold_selection=None,
    )

    assert result.trade_count == 1
    assert result.trades[0].entry_date == bars[2].trade_date
    assert result.trades[0].exit_date == bars[3].trade_date
    assert result.trades[0].exit_reason == "stop_loss"
    assert result.same_day_exit_count == 0


def test_score_and_trend_exit_thresholds_are_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars = make_daily_bars("SSE:513300", count=130)
    features = _passing_features().model_copy(update={"score": 0.05, "trend_strength": 0.01})
    monkeypatch.setattr(
        profit_validation_module,
        "_signal_features",
        lambda *_args, **_kwargs: features,
    )
    position = profit_validation_module._OpenPosition(
        entry_index=125,
        entry_date=bars[125].trade_date,
        entry_price=bars[125].open_price,
        shares=1.0,
        signal_score=0.50,
        predicted_probability=0.625,
        position_fraction=1.0,
        trailing_peak=bars[125].open_price,
    )

    baseline = profit_validation_module._close_signal_reason(
        index=126,
        closes=tuple(bar.close_price for bar in bars),
        bar=bars[126],
        position=position,
        parameters=horizon_parameters(HorizonPreset.ONE_MONTH),
        config=ProfitSeekingConfig(stop_loss_pct=0.50),
    )
    responsive = profit_validation_module._close_signal_reason(
        index=126,
        closes=tuple(bar.close_price for bar in bars),
        bar=bars[126],
        position=position,
        parameters=horizon_parameters(HorizonPreset.ONE_MONTH),
        config=ProfitSeekingConfig(
            score_exit_threshold=0.10,
            trend_exit_threshold=0.00,
            stop_loss_pct=0.50,
        ),
    )

    assert baseline is None
    assert responsive == "score_breakdown"


def test_a_share_one_price_limits_block_buy_and_sell_but_not_etf() -> None:
    config = profit_strategy_config("short_term", HorizonPreset.ONE_MONTH, 12)
    previous_close = 10.0
    ordinary_bar = make_daily_bars("SSE:600519", count=1)[0]
    limit_up = ordinary_bar.model_copy(
        update={
            "open_price": 11.0,
            "high_price": 11.0,
            "low_price": 11.0,
            "close_price": 11.0,
        }
    )
    limit_down = ordinary_bar.model_copy(
        update={
            "open_price": 9.0,
            "high_price": 9.0,
            "low_price": 9.0,
            "close_price": 9.0,
        }
    )

    assert (
        profit_validation_module._a_share_execution_block_reason(
            security_id="SSE:600519",
            side="BUY",
            previous_close=previous_close,
            bar=limit_up,
            config=config,
        )
        == "one_price_limit_up"
    )
    assert (
        profit_validation_module._a_share_execution_block_reason(
            security_id="SSE:600519",
            side="SELL",
            previous_close=previous_close,
            bar=limit_down,
            config=config,
        )
        == "one_price_limit_down"
    )
    assert (
        profit_validation_module._a_share_execution_block_reason(
            security_id="SSE:513300",
            side="BUY",
            previous_close=previous_close,
            bar=limit_up,
            config=config,
        )
        is None
    )


def test_a_share_limit_up_rejection_and_limit_down_exit_deferral_are_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = list(make_daily_bars("SSE:600519", count=8))
    entry_previous_close = base[1].close_price
    limit_up_price = entry_previous_close * 1.10
    limit_up_bars = base.copy()
    limit_up_bars[2] = limit_up_bars[2].model_copy(
        update={
            "open_price": limit_up_price,
            "high_price": limit_up_price,
            "low_price": limit_up_price,
            "close_price": limit_up_price,
        }
    )
    config = profit_strategy_config(
        "short_term",
        HorizonPreset.ONE_MONTH,
        252,
    ).model_copy(
        update={
            "stop_loss_pct": 0.50,
            "apply_a_share_market_regime_filter": False,
        }
    )

    def entry_features(index: int, **_kwargs: object) -> ProfitSignalFeatures | None:
        return _passing_features(base[index].trade_date) if index == 1 else None

    monkeypatch.setattr(profit_validation_module, "_signal_features", entry_features)
    monkeypatch.setattr(
        profit_validation_module,
        "_close_signal_reason",
        lambda **_kwargs: None,
    )
    rejected = profit_validation_module._simulate_strategy(
        security_id="SSE:600519",
        bars=tuple(limit_up_bars),
        config=config,
        parameters=horizon_parameters(HorizonPreset.ONE_MONTH),
        start_index=1,
        end_index=6,
        threshold=0.10,
        threshold_selection=None,
    )

    assert rejected.trade_count == 0
    assert rejected.entry_rejection_count == 1

    limit_down_bars = base.copy()
    exit_previous_close = limit_down_bars[2].close_price
    limit_down_price = exit_previous_close * 0.90
    limit_down_bars[3] = limit_down_bars[3].model_copy(
        update={
            "open_price": limit_down_price,
            "high_price": limit_down_price,
            "low_price": limit_down_price,
            "close_price": limit_down_price,
        }
    )

    def close_after_entry(*, index: int, **_kwargs: object) -> str | None:
        return "score_breakdown" if index == 2 else None

    monkeypatch.setattr(profit_validation_module, "_close_signal_reason", close_after_entry)
    deferred = profit_validation_module._simulate_strategy(
        security_id="SSE:600519",
        bars=tuple(limit_down_bars),
        config=config,
        parameters=horizon_parameters(HorizonPreset.ONE_MONTH),
        start_index=1,
        end_index=6,
        threshold=0.10,
        threshold_selection=None,
    )

    assert deferred.trade_count == 1
    assert deferred.trades[0].exit_date == limit_down_bars[4].trade_date
    assert deferred.next_open_exit_count == 1
    assert deferred.exit_deferral_count == 1
    assert deferred.same_day_exit_count == 0


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
    assert result.stress_round_trip_cost_bps is not None
    assert result.stress_round_trip_cost_bps >= 30
    assert result.stress_total_return is not None
    assert result.stress_total_return <= result.total_return
    assert result.cost_stress_passed is not None
    assert result.reliability_grade.value in {"A", "B", "C", "N"}
    assert result.walk_forward_active_folds > 0
    assert result.walk_forward_participation_ratio is not None
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
    assert len(report.data_snapshots) == 10
    assert report.data_snapshots[0].bar_count == 900
    assert report.data_snapshots[0].providers == ("fixture",)
    assert report.data_snapshots[0].adjustments == (AdjustmentMode.NONE,)
    assert len(report.data_snapshots[0].checksum) == 64
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
    assert single_evidence.cost_stress_passed == report.results[1].cost_stress_passed
    assert (
        single_evidence.walk_forward_participation_ratio
        == report.results[1].walk_forward_participation_ratio
    )
    assert (
        single_evidence.walk_forward_positive_ratio == report.results[1].walk_forward_positive_ratio
    )
    summary = report_summary(report, provider_id="fixture")
    assert summary["provider"] == "fixture"
    summary_results = summary["results"]
    assert isinstance(summary_results, list)
    assert len(summary_results) == 10
    assert summary_results[0]["walk_forward_positive_ratio"] is not None
    assert summary_results[0]["next_open_exit_count"] >= 0
    assert summary_results[0]["same_day_exit_count"] >= 0
    assert summary_results[0]["entry_rejection_count"] >= 0
    assert summary_results[0]["exit_deferral_count"] >= 0
    assert summary_results[0]["t_plus_one_deferral_count"] >= 0


def test_mixed_validation_universe_covers_stocks_and_etfs() -> None:
    universe = default_mixed_validation_universe()

    assert len(universe) == 10
    assert sum(member.asset_type.value == "STOCK" for member in universe) == 5
    assert sum(member.asset_type.value == "ETF" for member in universe) == 5
    assert {member.security_id for member in universe} >= {
        "SSE:600519",
        "SSE:513300",
    }


def test_a_share_validation_universe_has_ten_industry_buckets() -> None:
    universe = default_a_share_validation_universe()

    assert len(universe) == 10
    assert all(member.asset_type.value == "STOCK" for member in universe)
    assert len({member.asset_bucket for member in universe}) == 10
    assert {member.security_id for member in universe} >= {
        "SSE:600519",
        "SSE:600030",
        "SZSE:300059",
        "SSE:601899",
    }


def test_a_share_validation_pools_are_fixed_and_disjoint() -> None:
    primary = default_a_share_validation_universe()
    confirmation = default_a_share_confirmation_universe()
    shadow = default_a_share_shadow_universe()

    assert len(primary) == len(confirmation) == len(shadow) == 10
    assert all(member.asset_type.value == "STOCK" for member in (*confirmation, *shadow))
    primary_ids = {member.security_id for member in primary}
    confirmation_ids = {member.security_id for member in confirmation}
    shadow_ids = {member.security_id for member in shadow}
    assert primary_ids.isdisjoint(confirmation_ids)
    assert primary_ids.isdisjoint(shadow_ids)
    assert confirmation_ids.isdisjoint(shadow_ids)


def test_validation_lab_requests_forward_adjusted_history() -> None:
    member = default_etf_validation_universe()[0]

    class CapturingProvider:
        provider_id = "capture"

        def __init__(self) -> None:
            self.requests: list[BarsRequest] = []

        async def get_bars(self, request: BarsRequest) -> list[Bar]:
            self.requests.append(request)
            return list(make_daily_bars(member.security_id))

    provider = CapturingProvider()
    report, failures = asyncio.run(
        validate_profit_universe(provider, universe=(member,), history_years=3)  # type: ignore[arg-type]
    )

    assert failures == ()
    assert report.results
    request = provider.requests[0]
    assert request.adjustment is AdjustmentMode.FORWARD


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


def test_one_day_spike_filter_is_configurable_and_explained() -> None:
    config = ProfitSeekingConfig(
        horizon=HorizonPreset.ONE_MONTH,
        max_trades_per_year=8,
        minimum_oos_bars=80,
        minimum_validation_bars=80,
        minimum_trades_for_pass=1,
        max_one_day_return_for_entry=0.05,
    )

    result = run_profit_strategy_backtest(
        "SSE:513300",
        make_daily_bars(regime="late_rally"),
        config=config,
    )

    assert "单日涨幅超过5%时不在次日追入" in " ".join(result.notes)


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


def test_market_regime_filter_is_configurable_and_explained() -> None:
    config = ProfitSeekingConfig(
        horizon=HorizonPreset.ONE_MONTH,
        max_trades_per_year=8,
        minimum_oos_bars=80,
        minimum_validation_bars=80,
        minimum_trades_for_pass=1,
        minimum_regime_momentum=0.0,
        minimum_regime_trend_strength=0.0,
    )

    result = run_profit_strategy_backtest("SSE:513300", make_daily_bars(), config=config)

    notes = " ".join(result.notes)
    assert "中期状态收益低于0%时不新开仓" in notes
    assert "价格相对中期均线低于0%时不新开仓" in notes


def test_volatility_target_scales_exposure_without_leverage() -> None:
    base_config = ProfitSeekingConfig(
        horizon=HorizonPreset.ONE_MONTH,
        max_trades_per_year=8,
        minimum_oos_bars=80,
        minimum_validation_bars=80,
        minimum_trades_for_pass=1,
    )
    scaled_config = base_config.model_copy(
        update={
            "target_annual_volatility": 0.10,
            "minimum_position_fraction": 0.25,
            "maximum_position_fraction": 1.0,
        }
    )
    bars = make_daily_bars(regime="volatile_trend")

    baseline = run_profit_strategy_backtest("SSE:513300", bars, config=base_config)
    scaled = run_profit_strategy_backtest("SSE:513300", bars, config=scaled_config)

    assert baseline.trade_count > 0
    assert scaled.trade_count == baseline.trade_count
    assert scaled.average_position_fraction is not None
    assert scaled.average_position_fraction < 1.0
    assert all(0.25 <= trade.position_fraction <= 1.0 for trade in scaled.trades)
    assert scaled.turnover < baseline.turnover
    assert scaled.max_drawdown >= baseline.max_drawdown
    assert "不使用杠杆" in " ".join(scaled.notes)


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
    assert panel.average_position_fraction != "--"
    assert panel.sharpe_ratio != "--"
    assert panel.walk_forward_consistency != "--"
    assert panel.cost_stress != "--"
    assert "次日开盘退出" in panel.execution_realism
    assert "同日退出" in panel.execution_realism
    assert "止损无日内先后前视" in panel.execution_realism
    assert panel.trades
    assert "买入" in panel.trades[0]
    assert "卖出" in panel.trades[0]
    assert "收益" in panel.trades[0]
    assert "暴露" in panel.trades[0]


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
