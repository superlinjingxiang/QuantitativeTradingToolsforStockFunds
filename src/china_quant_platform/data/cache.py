"""Parquet-backed historical market data cache."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, time, timedelta
from pathlib import Path
from urllib.parse import quote

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import ValidationError

from china_quant_platform.data.provider import BarsRequest
from china_quant_platform.domain import (
    AdjustmentMode,
    Bar,
    BarInterval,
    DataInvalid,
)
from china_quant_platform.domain.base import DomainModel

SESSION_START = time(9, 30)
SESSION_END = time(15, 0)


class BarCacheAppendResult(DomainModel):
    inserted_count: int
    skipped_duplicate_count: int
    partitions_written: tuple[str, ...]


class HistoricalBarCache:
    """Stores normalized bars in security/interval/year Parquet partitions."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def partition_path(
        self,
        security_id: str,
        interval: BarInterval,
        adjustment: AdjustmentMode,
        year: int,
    ) -> Path:
        return (
            self.root
            / "bars"
            / f"security_id={_partition_value(security_id)}"
            / f"interval={_partition_value(interval.value)}"
            / f"adjustment={_partition_value(adjustment.value)}"
            / f"year={year}"
            / "bars.parquet"
        )

    def append_bars(self, bars: Sequence[Bar]) -> BarCacheAppendResult:
        if not bars:
            return BarCacheAppendResult(
                inserted_count=0,
                skipped_duplicate_count=0,
                partitions_written=(),
            )

        _ensure_unique_bar_keys(bars)

        grouped: dict[Path, list[Bar]] = defaultdict(list)
        for bar in bars:
            grouped[
                self.partition_path(
                    bar.security_id,
                    bar.interval,
                    bar.adjustment,
                    bar.start_time.year,
                )
            ].append(bar)

        inserted_count = 0
        skipped_duplicate_count = 0
        written_paths: list[str] = []

        for path, incoming_bars in grouped.items():
            existing_bars = self._read_partition(path)
            _ensure_unique_bar_keys(existing_bars)
            existing_by_key = {_bar_key(bar): bar for bar in existing_bars}

            merged_bars = list(existing_bars)
            partition_inserted = 0
            for bar in incoming_bars:
                key = _bar_key(bar)
                existing = existing_by_key.get(key)
                if existing is None:
                    merged_bars.append(bar)
                    existing_by_key[key] = bar
                    partition_inserted += 1
                    continue
                if existing.to_contract_dict() != bar.to_contract_dict():
                    raise DataInvalid(
                        "Conflicting duplicate bar for "
                        f"{bar.security_id} {bar.interval.value} {bar.start_time.isoformat()}"
                    )
                skipped_duplicate_count += 1

            if partition_inserted:
                self._write_partition(path, sorted(merged_bars, key=lambda bar: bar.start_time))
                written_paths.append(str(path))
                inserted_count += partition_inserted

        return BarCacheAppendResult(
            inserted_count=inserted_count,
            skipped_duplicate_count=skipped_duplicate_count,
            partitions_written=tuple(sorted(written_paths)),
        )

    def read_bars(self, request: BarsRequest) -> list[Bar]:
        bars: list[Bar] = []
        for year in range(request.start_time.year, request.end_time.year + 1):
            path = self.partition_path(
                request.security_id,
                request.interval,
                request.adjustment,
                year,
            )
            bars.extend(self._read_partition(path))

        filtered = [
            bar
            for bar in bars
            if bar.security_id == request.security_id
            and bar.interval is request.interval
            and bar.adjustment is request.adjustment
            and request.start_time <= bar.start_time
            and bar.end_time <= request.end_time
        ]
        _ensure_unique_bar_keys(filtered)
        return sorted(filtered, key=lambda bar: bar.start_time)

    def missing_ranges(self, request: BarsRequest) -> list[BarsRequest]:
        cached_bars = self.read_bars(request)
        expected_windows = _expected_windows(request)
        if not expected_windows:
            return [] if cached_bars else [request]

        cached_starts = {bar.start_time for bar in cached_bars}
        missing_indices = [
            index
            for index, (window_start, _window_end) in enumerate(expected_windows)
            if window_start not in cached_starts
        ]
        if not missing_indices:
            return []

        ranges: list[BarsRequest] = []
        group_start = missing_indices[0]
        previous = group_start
        for index in missing_indices[1:]:
            if index == previous + 1:
                previous = index
                continue
            ranges.append(
                _request_for_window_group(request, expected_windows, group_start, previous)
            )
            group_start = previous = index
        ranges.append(_request_for_window_group(request, expected_windows, group_start, previous))
        return ranges

    def _read_partition(self, path: Path) -> list[Bar]:
        if not path.exists():
            return []

        try:
            table = pq.ParquetFile(path).read()
            return [Bar.from_contract_dict(row) for row in table.to_pylist()]
        except (pa.ArrowException, ValidationError) as exc:
            raise DataInvalid(f"Invalid bar cache partition {path}: {exc}") from exc

    def _write_partition(self, path: Path, bars: Sequence[Bar]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [bar.to_contract_dict() for bar in bars]
        pq.write_table(pa.Table.from_pylist(rows), path)


def _partition_value(value: str) -> str:
    return quote(value, safe="._-")


def _bar_key(bar: Bar) -> tuple[str, str, str, datetime]:
    return (bar.security_id, bar.interval.value, bar.adjustment.value, bar.start_time)


def _ensure_unique_bar_keys(bars: Sequence[Bar]) -> None:
    seen: set[tuple[str, str, str, datetime]] = set()
    for bar in bars:
        key = _bar_key(bar)
        if key in seen:
            raise DataInvalid(
                "Duplicate bar for "
                f"{bar.security_id} {bar.interval.value} {bar.start_time.isoformat()}"
            )
        seen.add(key)


def _expected_windows(request: BarsRequest) -> list[tuple[datetime, datetime]]:
    if request.interval is BarInterval.DAILY:
        return _expected_daily_windows(request)

    step = _interval_step(request.interval)
    if step is None:
        return []

    windows: list[tuple[datetime, datetime]] = []
    current = request.start_time
    while current < request.end_time:
        window_end = current + step
        if window_end <= request.end_time:
            windows.append((current, window_end))
        current = window_end
    return windows


def _expected_daily_windows(request: BarsRequest) -> list[tuple[datetime, datetime]]:
    windows: list[tuple[datetime, datetime]] = []
    current_date = request.start_time.date()
    while current_date <= request.end_time.date():
        if current_date.weekday() < 5:
            window_start = datetime.combine(
                current_date,
                SESSION_START,
                tzinfo=request.start_time.tzinfo,
            )
            window_end = datetime.combine(
                current_date,
                SESSION_END,
                tzinfo=request.end_time.tzinfo,
            )
            if window_start >= request.start_time and window_end <= request.end_time:
                windows.append((window_start, window_end))
        current_date += timedelta(days=1)
    return windows


def _interval_step(interval: BarInterval) -> timedelta | None:
    match interval:
        case BarInterval.TICK:
            return None
        case BarInterval.ONE_MINUTE:
            return timedelta(minutes=1)
        case BarInterval.FIVE_MINUTES:
            return timedelta(minutes=5)
        case BarInterval.FIFTEEN_MINUTES:
            return timedelta(minutes=15)
        case BarInterval.THIRTY_MINUTES:
            return timedelta(minutes=30)
        case BarInterval.SIXTY_MINUTES:
            return timedelta(minutes=60)
        case BarInterval.WEEKLY | BarInterval.MONTHLY:
            return None
        case BarInterval.DAILY:
            return timedelta(days=1)


def _request_for_window_group(
    request: BarsRequest,
    expected_windows: Sequence[tuple[datetime, datetime]],
    start_index: int,
    end_index: int,
) -> BarsRequest:
    return BarsRequest(
        security_id=request.security_id,
        interval=request.interval,
        start_time=expected_windows[start_index][0],
        end_time=expected_windows[end_index][1],
        adjustment=request.adjustment,
    )


__all__ = ["BarCacheAppendResult", "HistoricalBarCache"]
