"""Provider-backed, repeatable profitability validation for representative universes."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from china_quant_platform.data import BarsRequest, MarketDataProvider
from china_quant_platform.domain import AdjustmentMode, AssetType, Bar, BarInterval
from china_quant_platform.strategies.profit_validation import (
    DefaultValidationSecurity,
    HorizonPreset,
    ProfitValidationReport,
    default_a_share_confirmation_universe,
    default_a_share_shadow_universe,
    default_a_share_validation_universe,
    default_etf_validation_universe,
    default_mixed_validation_universe,
    horizon_parameters,
    profit_strategy_config,
    run_profit_validation_lab,
)


async def validate_default_profit_universe(
    provider: MarketDataProvider,
    *,
    horizon: HorizonPreset = HorizonPreset.ONE_MONTH,
    strategy_mode: str = "short_term",
    max_trades_per_year: int = 12,
    history_years: int = 7,
    as_of: datetime | None = None,
) -> tuple[ProfitValidationReport, tuple[str, ...]]:
    return await validate_profit_universe(
        provider,
        universe=default_etf_validation_universe(),
        horizon=horizon,
        strategy_mode=strategy_mode,
        max_trades_per_year=max_trades_per_year,
        history_years=history_years,
        as_of=as_of,
    )


async def validate_profit_universe(
    provider: MarketDataProvider,
    *,
    universe: Sequence[DefaultValidationSecurity],
    horizon: HorizonPreset = HorizonPreset.ONE_MONTH,
    strategy_mode: str = "short_term",
    max_trades_per_year: int = 12,
    history_years: int = 7,
    as_of: datetime | None = None,
) -> tuple[ProfitValidationReport, tuple[str, ...]]:
    if history_years < 1:
        raise ValueError("history_years must be at least 1")
    if strategy_mode not in {"short_term", "long_term"}:
        raise ValueError("strategy_mode must be short_term or long_term")
    end_time = as_of or datetime.now(UTC)
    if end_time.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    start_time = end_time - timedelta(days=365 * history_years + 30)
    config = profit_strategy_config(
        "long_term" if strategy_mode == "long_term" else "short_term",
        horizon,
        max_trades_per_year,
    )
    parameters = horizon_parameters(horizon)
    minimum_bars = parameters.warmup_bars + config.minimum_validation_bars + config.minimum_oos_bars
    bars_by_security: dict[str, tuple[Bar, ...]] = {}
    failures: list[str] = []
    for member in universe:
        try:
            bars = await provider.get_bars(
                BarsRequest(
                    security_id=member.security_id,
                    interval=BarInterval.DAILY,
                    start_time=start_time,
                    end_time=end_time,
                    adjustment=AdjustmentMode.FORWARD,
                )
            )
        except Exception as exc:  # pragma: no cover - provider exceptions vary.
            failures.append(f"{member.security_id}: {type(exc).__name__}: {exc}")
            continue
        bars_by_security[member.security_id] = tuple(bars)
        if len(bars) < minimum_bars:
            failures.append(
                f"{member.security_id}: insufficient history {len(bars)}/{minimum_bars} bars"
            )
    needs_market_regime = config.apply_a_share_market_regime_filter and any(
        member.asset_type is AssetType.STOCK for member in universe
    )
    if needs_market_regime and config.market_regime_security_id not in bars_by_security:
        try:
            market_bars = await provider.get_bars(
                BarsRequest(
                    security_id=config.market_regime_security_id,
                    interval=BarInterval.DAILY,
                    start_time=start_time,
                    end_time=end_time,
                    adjustment=AdjustmentMode.FORWARD,
                )
            )
        except Exception as exc:  # pragma: no cover - provider exceptions vary.
            failures.append(
                f"{config.market_regime_security_id}: market regime unavailable: "
                f"{type(exc).__name__}: {exc}"
            )
        else:
            bars_by_security[config.market_regime_security_id] = tuple(market_bars)
            if len(market_bars) <= config.market_regime_long_lookback:
                failures.append(
                    f"{config.market_regime_security_id}: market regime history "
                    f"{len(market_bars)}/{config.market_regime_long_lookback + 1} bars"
                )
    report = run_profit_validation_lab(
        bars_by_security,
        config=config,
        universe=universe,
    )
    return report, tuple(failures)


def report_summary(
    report: ProfitValidationReport,
    *,
    provider_id: str,
    failures: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "provider": provider_id,
        "config": report.config.to_contract_dict(),
        "data_snapshots": [snapshot.to_contract_dict() for snapshot in report.data_snapshots],
        "aggregate": report.aggregate.to_contract_dict(),
        "results": [
            {
                "security_id": result.security_id,
                "status": result.status.value,
                "grade": result.reliability_grade.value,
                "total_return": result.total_return,
                "annualized_return": result.annualized_return,
                "sharpe_ratio": result.sharpe_ratio,
                "calmar_ratio": result.calmar_ratio,
                "max_drawdown": result.max_drawdown,
                "benchmark_return": result.benchmark_total_return,
                "benchmark_max_drawdown": result.benchmark_max_drawdown,
                "excess_return": result.excess_return,
                "trade_count": result.trade_count,
                "average_position_fraction": result.average_position_fraction,
                "win_rate": result.win_rate,
                "brier_score": result.brier_score,
                "walk_forward_active_folds": result.walk_forward_active_folds,
                "walk_forward_participation_ratio": result.walk_forward_participation_ratio,
                "walk_forward_positive_ratio": result.walk_forward_positive_ratio,
                "walk_forward_excess_ratio": result.walk_forward_excess_ratio,
                "walk_forward_median_return": result.walk_forward_median_return,
                "stress_round_trip_cost_bps": result.stress_round_trip_cost_bps,
                "stress_total_return": result.stress_total_return,
                "stress_max_drawdown": result.stress_max_drawdown,
                "cost_stress_passed": result.cost_stress_passed,
                "next_open_exit_count": result.next_open_exit_count,
                "same_day_exit_count": result.same_day_exit_count,
                "entry_rejection_count": result.entry_rejection_count,
                "exit_deferral_count": result.exit_deferral_count,
                "t_plus_one_deferral_count": result.t_plus_one_deferral_count,
                "market_regime": result.market_regime.to_contract_dict(),
                "notes": result.notes,
            }
            for result in report.results
        ],
        "failures": list(failures),
        "checksum": report.checksum,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run profitability validation on the default 10-ETF universe."
    )
    parser.add_argument(
        "--strategy-mode",
        choices=("short_term", "long_term"),
        default="short_term",
    )
    parser.add_argument(
        "--horizon",
        choices=tuple(item.value for item in HorizonPreset),
        default=HorizonPreset.ONE_MONTH.value,
    )
    parser.add_argument("--max-trades", type=int, default=12)
    parser.add_argument("--history-years", type=int, default=7)
    parser.add_argument(
        "--universe",
        choices=("etf10", "stock10", "stock_confirm10", "stock_shadow10", "mixed10"),
        default="etf10",
        help=(
            "Use ten ETFs, the primary/confirmation/shadow A-share pools, "
            "or a five-stock/five-ETF validation pool."
        ),
    )
    args = parser.parse_args(argv)

    from china_quant_platform.data import create_default_market_data_provider

    provider = create_default_market_data_provider()

    async def run() -> tuple[ProfitValidationReport, tuple[str, ...]]:
        if args.universe == "stock10":
            universe = default_a_share_validation_universe()
        elif args.universe == "stock_confirm10":
            universe = default_a_share_confirmation_universe()
        elif args.universe == "stock_shadow10":
            universe = default_a_share_shadow_universe()
        elif args.universe == "mixed10":
            universe = default_mixed_validation_universe()
        else:
            universe = default_etf_validation_universe()
        return await validate_profit_universe(
            provider,
            universe=universe,
            horizon=HorizonPreset(args.horizon),
            strategy_mode=args.strategy_mode,
            max_trades_per_year=max(1, min(args.max_trades, 252)),
            history_years=args.history_years,
        )

    report, failures = asyncio.run(run())
    print(
        json.dumps(
            report_summary(report, provider_id=provider.provider_id, failures=failures),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
