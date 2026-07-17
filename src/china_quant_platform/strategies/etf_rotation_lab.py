"""Run the fixed-universe ETF rotation validation against provider data."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta

from china_quant_platform.data import BarsRequest, MarketDataProvider
from china_quant_platform.domain import AdjustmentMode, Bar, BarInterval
from china_quant_platform.strategies.etf_rotation_validation import (
    EtfRotationBacktestConfig,
    EtfRotationValidationReport,
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
    full: EtfRotationValidationReport,
    oos: EtfRotationValidationReport,
    failures: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "provider": provider_id,
        "security_ids": list(security_ids),
        "common_date_count": len(common_dates),
        "common_start": common_dates[0].isoformat(),
        "common_end": common_dates[-1].isoformat(),
        "oos_start": oos_start.isoformat(),
        "failures": list(failures),
        "full": full.to_contract_dict(),
        "oos25": oos.to_contract_dict(),
        "execution_boundary": {
            "signal": "prior_close",
            "execution": "next_open",
            "order_path": "research_only",
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the fixed ten-ETF rotation candidate with a final temporal holdout."
    )
    parser.add_argument("--history-years", type=int, default=9)
    parser.add_argument("--oos-fraction", type=float, default=0.25)
    args = parser.parse_args(argv)
    if not 0.1 <= args.oos_fraction <= 0.5:
        parser.error("--oos-fraction must be between 0.1 and 0.5")

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
    config = EtfRotationBacktestConfig()
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
    print(
        json.dumps(
            validation_summary(
                provider_id=provider.provider_id,
                security_ids=security_ids,
                common_dates=dates,
                oos_start=oos_start,
                full=full,
                oos=oos,
                failures=failures,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
