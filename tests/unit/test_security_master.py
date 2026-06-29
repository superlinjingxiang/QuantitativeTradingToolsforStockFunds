"""Security master and local search tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from time import perf_counter

import pytest
from pydantic import ValidationError

from china_quant_platform.data import (
    SecurityMasterRecord,
    SecurityMasterService,
)
from china_quant_platform.domain import (
    AssetType,
    Currency,
    Exchange,
    SecurityRef,
    SecurityStatus,
)


def selected_at(day: int = 29, minute: int = 0) -> datetime:
    return datetime(2026, 6, day, 9, minute, tzinfo=UTC)


def security(
    security_id: str,
    symbol: str,
    name: str,
    *,
    asset_type: AssetType = AssetType.STOCK,
    exchange: Exchange = Exchange.SSE,
    listed_date: date = date(2020, 1, 1),
    status_date: date = date(2026, 6, 28),
    status: SecurityStatus = SecurityStatus.ACTIVE,
    aliases: tuple[str, ...] = (),
) -> SecurityRef:
    return SecurityRef(
        security_id=security_id,
        symbol=symbol,
        name=name,
        asset_type=asset_type,
        exchange=exchange,
        currency=Currency.CNY,
        listed_date=listed_date,
        status_date=status_date,
        status=status,
        aliases=aliases,
    )


def sample_service() -> SecurityMasterService:
    return SecurityMasterService.from_securities(
        (
            security(
                "SSE:600519",
                "600519",
                "贵州茅台",
                aliases=("茅台", "Kweichow Moutai", "guizhou maotai"),
            ),
            security(
                "SSE:510300",
                "510300",
                "沪深300ETF",
                asset_type=AssetType.ETF,
                aliases=("300ETF", "CSI300 ETF"),
            ),
            security(
                "FUND:000001",
                "000001",
                "华夏成长混合",
                asset_type=AssetType.MUTUAL_FUND,
                exchange=Exchange.FUND_COMPANY,
                aliases=("Huaxia Growth",),
            ),
        )
    )


def test_search_by_code_name_and_alias_returns_typed_deduped_candidates() -> None:
    service = sample_service()

    by_code = service.search("600519")
    by_name = service.search("贵州茅台")
    by_alias = service.search("300ETF")

    assert [result.security.security_id for result in by_code] == ["SSE:600519"]
    assert [result.security.security_id for result in by_name] == ["SSE:600519"]
    assert [result.security.security_id for result in by_alias] == ["SSE:510300"]
    assert len({result.security.security_id for result in service.search("茅台")}) == 1


def test_fuzzy_search_matches_alias_subsequence() -> None:
    results = sample_service().search("gzmt")

    assert results[0].security.security_id == "SSE:600519"
    assert results[0].score > 0
    assert results[0].matched_fields


def test_security_master_resolves_point_in_time_status() -> None:
    service = SecurityMasterService.from_securities(
        (
            security(
                "SSE:600000",
                "600000",
                "浦发银行",
                status_date=date(2026, 1, 1),
                status=SecurityStatus.ACTIVE,
            ),
            security(
                "SSE:600000",
                "600000",
                "浦发银行",
                status_date=date(2026, 6, 1),
                status=SecurityStatus.SUSPENDED,
            ),
            security(
                "SSE:600000",
                "600000",
                "浦发银行",
                status_date=date(2026, 6, 10),
                status=SecurityStatus.ACTIVE,
            ),
        )
    )

    assert service.get_security("SSE:600000", as_of=date(2025, 12, 31)) is None

    active_before_suspension = service.get_security("SSE:600000", as_of=date(2026, 2, 1))
    suspended = service.get_security("SSE:600000", as_of=date(2026, 6, 5))
    active_after_resume = service.get_security("SSE:600000", as_of=date(2026, 6, 11))

    assert active_before_suspension is not None
    assert active_before_suspension.status is SecurityStatus.ACTIVE
    assert suspended is not None
    assert suspended.status is SecurityStatus.SUSPENDED
    assert active_after_resume is not None
    assert active_after_resume.status is SecurityStatus.ACTIVE


def test_search_can_filter_inactive_statuses() -> None:
    service = SecurityMasterService.from_securities(
        (
            security(
                "SSE:600001",
                "600001",
                "测试暂停",
                status=SecurityStatus.SUSPENDED,
            ),
        )
    )

    assert service.search("600001", include_inactive=True)
    assert service.search("600001", include_inactive=False) == []


def test_select_security_records_recent_searches_as_lru() -> None:
    service = sample_service()

    service.select_security("SSE:600519", selected_at=selected_at(29, 1))
    service.select_security("SSE:510300", selected_at=selected_at(29, 2))
    service.select_security("SSE:600519", selected_at=selected_at(29, 3))

    assert [security.security_id for security in service.recent_searches()] == [
        "SSE:600519",
        "SSE:510300",
    ]
    assert [security.security_id for security in service.recent_searches(limit=1)] == ["SSE:600519"]


def test_recent_searches_are_snapshot_aware() -> None:
    service = SecurityMasterService.from_securities(
        (
            security(
                "SSE:688001",
                "688001",
                "上市后证券",
                listed_date=date(2026, 7, 1),
                status_date=date(2026, 7, 1),
            ),
        )
    )
    service.record_recent("SSE:688001", selected_at=selected_at())

    assert service.recent_searches(as_of=date(2026, 6, 30)) == []
    assert service.recent_searches(as_of=date(2026, 7, 1))[0].security_id == "SSE:688001"


def test_security_master_record_rejects_mixed_security_ids() -> None:
    with pytest.raises(ValidationError):
        SecurityMasterRecord(
            security_id="SSE:600519",
            snapshots=(
                security("SSE:600519", "600519", "贵州茅台"),
                security("SSE:510300", "510300", "沪深300ETF"),
            ),
        )


def test_local_search_p95_is_under_300ms_on_fixture() -> None:
    securities = tuple(
        security(
            f"SSE:{600000 + index:06d}",
            f"{600000 + index:06d}",
            f"测试证券{index:04d}",
            aliases=(f"fixture security {index:04d}",),
        )
        for index in range(2_000)
    )
    service = SecurityMasterService.from_securities(securities)
    queries = [f"{600000 + (index * 37 % 2_000):06d}" for index in range(80)]

    durations: list[float] = []
    for query in queries:
        started_at = perf_counter()
        assert service.search(query, limit=5)
        durations.append(perf_counter() - started_at)

    p95 = sorted(durations)[int(len(durations) * 0.95) - 1]
    assert p95 < 0.300
