"""Market overview and breadth tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from china_quant_platform.domain import Quote, RecordQualityStatus
from china_quant_platform.market import (
    MarketTrendState,
    MarketVolatilityState,
    build_market_overview,
)


def as_of(minute: int = 0) -> datetime:
    return datetime(2026, 6, 29, 15, minute, tzinfo=UTC)


def quote(
    security_id: str,
    latest_price: float,
    previous_close: float,
    *,
    amount: float = 10_000_000,
    source_time: datetime | None = None,
) -> Quote:
    source = source_time or as_of()
    return Quote(
        security_id=security_id,
        latest_price=latest_price,
        previous_close=previous_close,
        open_price=previous_close,
        high_price=max(latest_price, previous_close),
        low_price=min(latest_price, previous_close),
        volume=100_000,
        amount=amount,
        provider="fixture",
        schema_version="v1",
        source_time=source,
        observed_at=source,
        received_at=source + timedelta(seconds=1),
        quality_status=RecordQualityStatus.OK,
    )


def test_market_overview_calculates_indices_breadth_turnover_and_states() -> None:
    overview = build_market_overview(
        index_quotes=(
            quote("INDEX:399001", 10_200, 10_000, amount=200_000_000),
            quote("INDEX:000001", 3_060, 3_000, amount=100_000_000),
        ),
        constituent_quotes=(
            quote("SSE:600001", 105, 100, amount=30_000_000),
            quote("SSE:600002", 102, 100, amount=20_000_000),
            quote("SSE:600003", 99, 100, amount=10_000_000),
            quote("SSE:600004", 100, 100, amount=5_000_000),
        ),
        as_of=as_of(),
        index_names={"INDEX:000001": "上证指数", "INDEX:399001": "深证成指"},
    )

    assert tuple(index.security_id for index in overview.indices) == (
        "INDEX:000001",
        "INDEX:399001",
    )
    assert overview.indices[0].name == "上证指数"
    assert overview.indices[0].change_pct == pytest.approx(0.02)
    assert overview.breadth.advancers == 2
    assert overview.breadth.decliners == 1
    assert overview.breadth.unchanged == 1
    assert overview.breadth.total_turnover == 65_000_000
    assert overview.breadth.volatility_state is MarketVolatilityState.NORMAL
    assert overview.breadth.trend_state is MarketTrendState.RISK_ON
    assert overview.data_health.block_signal is False


def test_market_overview_marks_stale_quotes_as_blocking_health() -> None:
    overview = build_market_overview(
        index_quotes=(
            quote("INDEX:000001", 3_000, 3_000, source_time=as_of() - timedelta(minutes=6)),
        ),
        constituent_quotes=(),
        as_of=as_of(),
        stale_after_seconds=300,
    )

    assert overview.data_health.block_signal is True
    assert "INDEX:000001" in overview.data_health.issues[0]
