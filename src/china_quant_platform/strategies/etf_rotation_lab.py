"""Run the fixed-universe ETF rotation validation against provider data."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta

from china_quant_platform.data import BarsRequest, MarketDataProvider
from china_quant_platform.domain import AdjustmentMode, Bar, BarInterval
from china_quant_platform.strategies.etf_capacity_validation import (
    EtfCapacityAuditReport,
    audit_etf_rotation_capacity,
    classify_etf_trading_system,
)
from china_quant_platform.strategies.etf_rotation_validation import (
    EtfExposureScalingModel,
    EtfMomentumSignalModel,
    EtfRotationBacktestConfig,
    EtfRotationShadowComparisonReport,
    EtfRotationShadowValidationConfig,
    EtfRotationValidationReport,
    compare_etf_rotation_shadow_episodes,
    validate_etf_rotation_strategy,
)
from china_quant_platform.strategies.profit_validation import (
    DefaultValidationSecurity,
    default_etf_validation_universe,
)


async def fetch_etf_rotation_history(
    provider: MarketDataProvider,
    *,
    universe: Sequence[DefaultValidationSecurity],
    history_years: int = 9,
    as_of: datetime | None = None,
) -> tuple[dict[str, tuple[Bar, ...]], tuple[str, ...]]:
    if history_years < 3:
        raise ValueError("history_years must be at least 3")
    end_time = as_of or datetime.now(UTC)
    if end_time.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    start_time = end_time - timedelta(days=365 * history_years + 30)
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
    return bars_by_security, tuple(failures)


def common_trade_dates(
    bars_by_security: Mapping[str, Sequence[Bar]],
    *,
    security_ids: Sequence[str],
) -> tuple[date, ...]:
    identifiers = tuple(dict.fromkeys(security_ids))
    if not identifiers:
        return ()
    missing = [security_id for security_id in identifiers if not bars_by_security.get(security_id)]
    if missing:
        raise ValueError(f"missing fixed-universe ETF history: {', '.join(missing)}")
    return tuple(
        sorted(
            set.intersection(
                *(
                    {bar.trade_date for bar in bars_by_security[security_id]}
                    for security_id in identifiers
                )
            )
        )
    )


def validation_summary(
    *,
    provider_id: str,
    security_ids: Sequence[str],
    common_dates: Sequence[date],
    oos_start: date,
    oos_fraction: float,
    full: EtfRotationValidationReport,
    oos: EtfRotationValidationReport,
    capacity: EtfCapacityAuditReport,
    shadow_comparison: EtfRotationShadowComparisonReport | None = None,
    shadow_oos_comparison: EtfRotationShadowComparisonReport | None = None,
    failures: Sequence[str] = (),
) -> dict[str, object]:
    result: dict[str, object] = {
        "provider": provider_id,
        "security_ids": list(security_ids),
        "common_date_count": len(common_dates),
        "common_start": common_dates[0].isoformat(),
        "common_end": common_dates[-1].isoformat(),
        "oos_start": oos_start.isoformat(),
        "oos_fraction": oos_fraction,
        "failures": list(failures),
        "full": full.to_contract_dict(),
        "oos": oos.to_contract_dict(),
        "capacity": capacity.to_contract_dict(),
        "execution_boundary": {
            "signal": "prior_close",
            "execution": "next_open",
            "order_path": "research_only",
        },
    }
    if shadow_comparison is not None:
        result["shadow_comparison"] = shadow_comparison.to_contract_dict()
    if shadow_oos_comparison is not None:
        result["shadow_oos_comparison"] = shadow_oos_comparison.to_contract_dict()
    return result


def compact_validation_summary(summary: Mapping[str, object]) -> dict[str, object]:
    """Return the decision-relevant metrics without equity-curve payloads."""

    full = summary["full"]
    oos = summary["oos"]
    capacity = summary["capacity"]
    if not isinstance(full, dict) or not isinstance(oos, dict) or not isinstance(capacity, dict):
        raise TypeError("validation summary contains invalid report payloads")
    result: dict[str, object] = {
        "provider": summary["provider"],
        "security_ids": summary["security_ids"],
        "common_date_count": summary["common_date_count"],
        "common_start": summary["common_start"],
        "common_end": summary["common_end"],
        "oos_start": summary["oos_start"],
        "oos_fraction": summary["oos_fraction"],
        "failures": summary["failures"],
        "full": _compact_rotation_report(full),
        "oos": _compact_rotation_report(oos),
        "capacity": {
            "model_version": capacity["config"]["model_version"],
            "as_of_date": capacity["as_of_date"],
            "reference_scenario": capacity["reference_scenario"],
            "scenarios": capacity["scenarios"],
            "maximum_supported_capital": capacity["maximum_supported_capital"],
            "hard_maximum_supported_capital": capacity["hard_maximum_supported_capital"],
            "trading_systems": capacity["trading_systems"],
            "missing_observations": [
                observation
                for observation in capacity["observations"]
                if observation["missing_reason"] is not None
            ],
            "notes": capacity["notes"],
        },
        "execution_boundary": summary["execution_boundary"],
    }
    for shadow_key in ("shadow_comparison", "shadow_oos_comparison"):
        shadow = summary.get(shadow_key)
        if isinstance(shadow, dict):
            episodes = shadow["episodes"]
            if not isinstance(episodes, (list, tuple)):
                raise TypeError("shadow comparison contains invalid episode payloads")
            compact_shadow = {key: value for key, value in shadow.items() if key != "episodes"}
            compact_shadow["episode_dates"] = [
                {
                    "episode_id": episode["episode_id"],
                    "execution_date": episode["execution_date"],
                    "evaluation_end": episode["evaluation_end"],
                }
                for episode in episodes
                if isinstance(episode, dict)
            ]
            result[shadow_key] = compact_shadow
    return result


def _compact_rotation_report(report: Mapping[str, object]) -> dict[str, object]:
    config = report["config"]
    base = report["base"]
    stress = report["stress"]
    folds = report["walk_forward_folds"]
    if (
        not isinstance(config, dict)
        or not isinstance(base, dict)
        or not isinstance(stress, dict)
        or not isinstance(folds, (list, tuple))
    ):
        raise TypeError("rotation report contains invalid backtest payloads")
    metric_keys = (
        "evaluation_start",
        "evaluation_end",
        "total_return",
        "annualized_return",
        "max_drawdown",
        "sharpe_ratio",
        "equal_weight_benchmark_return",
        "excess_return",
        "rebalance_count",
        "active_rebalance_count",
        "average_position_fraction",
        "cumulative_turnover",
        "average_rebalance_turnover",
        "cumulative_transaction_cost",
        "round_trip_cost_bps",
        "selection_counts",
    )
    return {
        "status": report["status"],
        "signal": {
            "model": config["signal_model"],
            "formation_lookback_bars": config["formation_lookback_bars"],
            "confirmation_lookback_bars": config["confirmation_lookback_bars"],
            "skip_recent_bars": config["skip_recent_bars"],
        },
        "exposure": {
            "model": config["exposure_model"],
            "volatility_lookback_bars": config["volatility_lookback_bars"],
            "target_annual_volatility": config["target_annual_volatility"],
            "min_position_fraction": config["min_position_fraction"],
            "max_position_fraction": config["max_position_fraction"],
        },
        "base": {key: base[key] for key in metric_keys},
        "stress": {key: stress[key] for key in metric_keys},
        "walk_forward_fold_count": len(folds),
        "walk_forward_positive_ratio": report["walk_forward_positive_ratio"],
        "walk_forward_excess_ratio": report["walk_forward_excess_ratio"],
        "notes": report["notes"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the fixed ten-ETF rotation candidate with a final temporal holdout."
    )
    parser.add_argument("--history-years", type=int, default=9)
    parser.add_argument("--oos-fraction", type=float, default=0.25)
    parser.add_argument(
        "--signal-model",
        choices=tuple(model.value for model in EtfMomentumSignalModel),
        default=EtfMomentumSignalModel.SINGLE_HORIZON.value,
        help="Momentum signal model to validate without changing production defaults.",
    )
    parser.add_argument(
        "--exposure-model",
        choices=tuple(model.value for model in EtfExposureScalingModel),
        default=EtfExposureScalingModel.INVERSE_VOLATILITY.value,
        help="Exposure scaling model to validate without changing production defaults.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print decision-relevant metrics without equity curves and rebalance details.",
    )
    parser.add_argument(
        "--shadow-compare-v13",
        action="store_true",
        help="Compare V10 and V13 over non-overlapping rebalance episodes.",
    )
    args = parser.parse_args(argv)
    if not 0.1 <= args.oos_fraction <= 0.5:
        parser.error("--oos-fraction must be between 0.1 and 0.5")
    if (
        args.shadow_compare_v13
        and args.exposure_model != EtfExposureScalingModel.INVERSE_VARIANCE.value
    ):
        parser.error("--shadow-compare-v13 requires --exposure-model INVERSE_VARIANCE")

    from china_quant_platform.data import create_default_market_data_provider

    provider = create_default_market_data_provider()
    universe = default_etf_validation_universe()
    bars_by_security, failures = asyncio.run(
        fetch_etf_rotation_history(
            provider,
            universe=universe,
            history_years=args.history_years,
        )
    )
    security_ids = tuple(member.security_id for member in universe)
    dates = common_trade_dates(bars_by_security, security_ids=security_ids)
    config = EtfRotationBacktestConfig(
        signal_model=EtfMomentumSignalModel(args.signal_model),
        exposure_model=EtfExposureScalingModel(args.exposure_model),
    )
    minimum_dates = config.formation_lookback_bars + config.walk_forward_window_bars + 2
    if len(dates) < minimum_dates:
        raise ValueError(f"insufficient common ETF history: {len(dates)}/{minimum_dates}")
    oos_start = dates[int(len(dates) * (1.0 - args.oos_fraction))]
    full = validate_etf_rotation_strategy(
        bars_by_security,
        security_ids=security_ids,
        config=config,
    )
    oos = validate_etf_rotation_strategy(
        bars_by_security,
        security_ids=security_ids,
        config=config,
        evaluation_start=oos_start,
    )
    capacity = audit_etf_rotation_capacity(
        bars_by_security,
        rebalances=full.base.rebalances,
        trading_system_by_security={
            member.security_id: classify_etf_trading_system(
                member.security_id,
                asset_bucket=member.asset_bucket,
            )
            for member in universe
        },
    )
    shadow_comparison = None
    shadow_oos_comparison = None
    if args.shadow_compare_v13:
        shadow_comparison = compare_etf_rotation_shadow_episodes(
            bars_by_security,
            security_ids=security_ids,
            candidate_config=config,
        )
        shadow_oos_comparison = compare_etf_rotation_shadow_episodes(
            bars_by_security,
            security_ids=security_ids,
            candidate_config=config,
            validation_config=EtfRotationShadowValidationConfig(
                minimum_episode_count=12,
                minimum_downside_episode_count=3,
                minimum_downside_improvement_ratio=2 / 3,
                minimum_downside_loss_reduction=0.10,
                minimum_upside_retention_ratio=0.65,
            ),
            evaluation_start=oos_start,
        )
    summary = validation_summary(
        provider_id=provider.provider_id,
        security_ids=security_ids,
        common_dates=dates,
        oos_start=oos_start,
        oos_fraction=args.oos_fraction,
        full=full,
        oos=oos,
        capacity=capacity,
        shadow_comparison=shadow_comparison,
        shadow_oos_comparison=shadow_oos_comparison,
        failures=failures,
    )
    if args.compact:
        summary = compact_validation_summary(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
