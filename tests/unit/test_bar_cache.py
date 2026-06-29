"""Historical bar cache tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from china_quant_platform.data import BarsRequest, HistoricalBarCache
from china_quant_platform.domain import (
    AdjustmentMode,
    Bar,
    BarInterval,
    DataInvalid,
    RecordQualityStatus,
)


def aware_datetime(day: int, hour: int = 9, minute: int = 30) -> datetime:
    return datetime(2026, 6, day, hour, minute, tzinfo=UTC)


def make_daily_bar(day: int, *, close_price: float = 101.0) -> Bar:
    start_time = aware_datetime(day, 9, 30)
    end_time = aware_datetime(day, 15, 0)
    return Bar(
        security_id="SSE:600519",
        interval=BarInterval.DAILY,
        start_time=start_time,
        end_time=end_time,
        trade_date=date(2026, 6, day),
        open_price=100,
        high_price=max(102, close_price),
        low_price=99,
        close_price=close_price,
        volume=10_000,
        amount=1_000_000,
        adjustment=AdjustmentMode.NONE,
        provider="fixture",
        schema_version="v1",
        source_time=end_time,
        observed_at=end_time,
        received_at=end_time + timedelta(seconds=1),
        quality_status=RecordQualityStatus.OK,
    )


def daily_request(start_day: int, end_day: int) -> BarsRequest:
    return BarsRequest(
        security_id="SSE:600519",
        interval=BarInterval.DAILY,
        start_time=aware_datetime(start_day, 9, 30),
        end_time=aware_datetime(end_day, 16, 0),
    )


def test_bar_cache_writes_partitioned_parquet_and_reads_range(tmp_path: Path) -> None:
    cache = HistoricalBarCache(tmp_path)
    bars = [make_daily_bar(22), make_daily_bar(23)]

    result = cache.append_bars(bars)
    partition = cache.partition_path(
        "SSE:600519",
        BarInterval.DAILY,
        AdjustmentMode.NONE,
        2026,
    )

    assert partition.exists()
    assert result.inserted_count == 2
    assert result.partitions_written == (str(partition),)
    assert cache.read_bars(daily_request(22, 23)) == bars


def test_bar_cache_rejects_duplicate_timestamps_in_append(tmp_path: Path) -> None:
    cache = HistoricalBarCache(tmp_path)
    bar = make_daily_bar(22)

    with pytest.raises(DataInvalid):
        cache.append_bars([bar, bar])


def test_bar_cache_is_idempotent_for_exact_existing_records(tmp_path: Path) -> None:
    cache = HistoricalBarCache(tmp_path)
    bars = [make_daily_bar(22), make_daily_bar(23)]

    first = cache.append_bars(bars)
    second = cache.append_bars(bars)

    assert first.inserted_count == 2
    assert second.inserted_count == 0
    assert second.skipped_duplicate_count == 2
    assert cache.read_bars(daily_request(22, 23)) == bars


def test_bar_cache_detects_invalid_ohlc_in_partition(tmp_path: Path) -> None:
    cache = HistoricalBarCache(tmp_path)
    bar = make_daily_bar(22)
    row = bar.to_contract_dict()
    row["high_price"] = row["close_price"] - 1
    partition = cache.partition_path(
        "SSE:600519",
        BarInterval.DAILY,
        AdjustmentMode.NONE,
        2026,
    )
    partition.parent.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist([row]), partition)

    with pytest.raises(DataInvalid):
        cache.read_bars(daily_request(22, 22))


def test_bar_cache_missing_ranges_only_cover_uncached_business_days(tmp_path: Path) -> None:
    cache = HistoricalBarCache(tmp_path)
    cache.append_bars([make_daily_bar(22), make_daily_bar(24)])

    ranges = cache.missing_ranges(daily_request(22, 26))

    assert [(request.start_time.date(), request.end_time.date()) for request in ranges] == [
        (date(2026, 6, 23), date(2026, 6, 23)),
        (date(2026, 6, 25), date(2026, 6, 26)),
    ]
