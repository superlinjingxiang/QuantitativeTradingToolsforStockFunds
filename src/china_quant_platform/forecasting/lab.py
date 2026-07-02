"""Provider-backed validation lab for interval forecasts."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from china_quant_platform.data import BarsRequest, MarketDataProvider
from china_quant_platform.domain import AdjustmentMode, Bar, BarInterval
from china_quant_platform.forecasting.interval import (
    DEFAULT_INTERVAL_FORECAST_SECURITY_IDS,
    IntervalForecastValidationReport,
    validate_interval_forecast_universe,
)


async def validate_default_interval_forecast_universe(
    provider: MarketDataProvider,
    *,
    security_ids: Sequence[str] = DEFAULT_INTERVAL_FORECAST_SECURITY_IDS,
    horizon_days: int = 21,
    history_years: int = 6,
    as_of: datetime | None = None,
    adjustment: AdjustmentMode = AdjustmentMode.NONE,
    round_trip_cost_bps: float = 15.0,
) -> IntervalForecastValidationReport:
    """Fetch historical daily bars and validate the interval forecaster.

    This is the operational bridge between market data providers and the pure
    forecasting code. It keeps provider failures visible in report notes instead of
    silently treating missing symbols as successful validation.
    """

    if history_years < 1:
        raise ValueError("history_years must be at least 1")
    end_time = as_of or datetime.now(UTC)
    if end_time.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    start_time = end_time - timedelta(days=365 * history_years + 15)
    bars_by_security: dict[str, tuple[Bar, ...]] = {}
    failures: list[str] = []
    for security_id in security_ids:
        request = BarsRequest(
            security_id=security_id,
            interval=BarInterval.DAILY,
            start_time=start_time,
            end_time=end_time,
            adjustment=adjustment,
        )
        try:
            bars = await provider.get_bars(request)
        except Exception as exc:  # pragma: no cover - exact provider exceptions vary.
            failures.append(f"{security_id}: {type(exc).__name__}: {exc}")
            continue
        if len(bars) < horizon_days + 80:
            failures.append(f"{security_id}: 历史K线不足 {len(bars)} bars")
            continue
        bars_by_security[security_id] = tuple(bars)

    report = validate_interval_forecast_universe(
        bars_by_security,
        horizon_days=horizon_days,
        round_trip_cost_bps=round_trip_cost_bps,
    )
    notes = list(report.notes)
    notes.append(
        f"数据源：{provider.provider_id}；请求{len(tuple(security_ids))}个标的，"
        f"成功{len(bars_by_security)}个，失败{len(failures)}个。"
    )
    if failures:
        notes.append("失败标的：" + "；".join(failures[:8]))
    return report.model_copy(update={"notes": tuple(notes)})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate interval forecasts on default ETF universe."
    )
    parser.add_argument("--horizon-days", type=int, default=21)
    parser.add_argument("--history-years", type=int, default=6)
    parser.add_argument("--round-trip-cost-bps", type=float, default=15.0)
    args = parser.parse_args(argv)

    from china_quant_platform.data import create_default_market_data_provider

    async def run() -> IntervalForecastValidationReport:
        return await validate_default_interval_forecast_universe(
            create_default_market_data_provider(),
            horizon_days=args.horizon_days,
            history_years=args.history_years,
            round_trip_cost_bps=args.round_trip_cost_bps,
        )

    report = asyncio.run(run())
    print(
        json.dumps(
            report.model_dump(mode="json", exclude={"results"}),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
