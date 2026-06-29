"""Data quality gates for market data and signal blocking."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, Field

from china_quant_platform.data.cache import expected_bar_windows
from china_quant_platform.data.gateway import RealtimeSubscriptionState
from china_quant_platform.data.provider import BarsRequest
from china_quant_platform.domain import (
    Bar,
    DataHealth,
    DataHealthStatus,
    DataInvalid,
    DataStale,
    Quote,
    RecordQualityStatus,
    UnauthorizedData,
)
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import NonEmptyString


class DataQualitySeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


class DataQualityCheck(StrEnum):
    UNIQUENESS = "UNIQUENESS"
    FRESHNESS = "FRESHNESS"
    COMPLETENESS = "COMPLETENESS"
    CONSISTENCY = "CONSISTENCY"
    AUTHORIZATION = "AUTHORIZATION"
    REQUIRED_FIELDS = "REQUIRED_FIELDS"
    SOURCE_CHRONOLOGY = "SOURCE_CHRONOLOGY"


class DataQualityIssue(DomainModel):
    code: NonEmptyString
    check: DataQualityCheck
    severity: DataQualitySeverity
    message: NonEmptyString
    blocks_signal: bool
    record_key: str | None = None


class DataQualityPolicy(DomainModel):
    quote_stale_after: timedelta = timedelta(seconds=10)
    historical_stale_after: timedelta = timedelta(days=3)
    cross_source_price_tolerance: float = Field(default=0.01, ge=0)
    authorized_providers: frozenset[str] | None = None


class DataQualityReport(DomainModel):
    as_of: AwareDatetime
    health: DataHealth
    issues: tuple[DataQualityIssue, ...]


class DataQualityService:
    """Evaluates freshness, completeness, consistency, and authorization gates."""

    def __init__(self, policy: DataQualityPolicy | None = None) -> None:
        self.policy = policy or DataQualityPolicy()

    def evaluate_quote(
        self,
        quote: Quote,
        *,
        as_of: datetime,
        authorized_providers: Collection[str] | None = None,
    ) -> DataQualityReport:
        issues = self._quote_issues(quote, as_of, authorized_providers)
        return self._report(as_of, issues)

    def evaluate_bars(
        self,
        bars: Sequence[Bar],
        *,
        as_of: datetime,
        request: BarsRequest | None = None,
        authorized_providers: Collection[str] | None = None,
    ) -> DataQualityReport:
        issues: list[DataQualityIssue] = []
        issues.extend(self._bar_required_field_issues(bars))
        issues.extend(self._bar_uniqueness_issues(bars))
        issues.extend(self._bar_completeness_issues(bars, request))

        valid_source_times: list[tuple[datetime, datetime, str]] = []
        for bar in bars:
            key = _bar_record_key(bar)
            issues.extend(self._record_status_issues(bar, key))
            issues.extend(self._authorization_issues(bar, key, authorized_providers))
            issues.extend(self._bar_consistency_issues(bar))
            source_time = _get_datetime(bar, "source_time")
            start_time = _get_datetime(bar, "start_time")
            if source_time is not None and start_time is not None:
                valid_source_times.append((start_time, source_time, key))

        if valid_source_times:
            issues.extend(self._source_chronology_issues(valid_source_times))
            latest_source_time = max(
                source_time for _start, source_time, _key in valid_source_times
            )
            issues.extend(
                self._freshness_issues(
                    latest_source_time,
                    as_of,
                    self.policy.historical_stale_after,
                    key="bars",
                )
            )

        return self._report(as_of, issues)

    def reconcile_quotes(
        self,
        primary: Quote,
        secondary: Quote,
        *,
        as_of: datetime,
        authorized_providers: Collection[str] | None = None,
    ) -> DataQualityReport:
        issues = [
            *self._quote_issues(primary, as_of, authorized_providers),
            *self._quote_issues(secondary, as_of, authorized_providers),
        ]

        primary_security_id = _get_value(primary, "security_id")
        secondary_security_id = _get_value(secondary, "security_id")
        primary_price = _get_number(primary, "latest_price")
        secondary_price = _get_number(secondary, "latest_price")
        if primary_security_id != secondary_security_id:
            issues.append(
                _issue(
                    code="DQ-06-SECURITY-MISMATCH",
                    check=DataQualityCheck.CONSISTENCY,
                    message="Cross-source quote reconciliation used different securities.",
                    record_key=f"{primary_security_id}|{secondary_security_id}",
                )
            )
        elif primary_price is not None and secondary_price is not None:
            denominator = max(abs(primary_price), abs(secondary_price), 1e-12)
            relative_difference = abs(primary_price - secondary_price) / denominator
            if relative_difference > self.policy.cross_source_price_tolerance:
                issues.append(
                    _issue(
                        code="DQ-06-PRICE-MISMATCH",
                        check=DataQualityCheck.CONSISTENCY,
                        message=(
                            "Cross-source latest_price difference "
                            f"{relative_difference:.4f} exceeds tolerance."
                        ),
                        record_key=str(primary_security_id),
                    )
                )

        return self._report(as_of, issues)

    def evaluate_realtime_state(
        self,
        state: RealtimeSubscriptionState,
        *,
        as_of: datetime,
    ) -> DataQualityReport:
        health = state.as_data_health(as_of, self.policy.quote_stale_after)
        if not health.block_signal:
            return DataQualityReport(as_of=as_of, health=health, issues=())

        issue = _issue(
            code="DQ-02-REALTIME-STATE",
            check=DataQualityCheck.FRESHNESS,
            message="Realtime subscription state blocks new signals.",
            record_key=",".join(state.security_ids),
        )
        return self._report(as_of, [issue])

    def assert_signal_allowed(self, report: DataQualityReport) -> None:
        if not report.health.block_signal:
            return

        engineering_message = "; ".join(report.health.issues)
        match report.health.status:
            case DataHealthStatus.UNAUTHORIZED:
                raise UnauthorizedData(engineering_message)
            case DataHealthStatus.STALE:
                raise DataStale(engineering_message)
            case _:
                raise DataInvalid(engineering_message)

    def _quote_issues(
        self,
        quote: Quote,
        as_of: datetime,
        authorized_providers: Collection[str] | None,
    ) -> list[DataQualityIssue]:
        key = _quote_record_key(quote)
        issues = [
            *self._required_field_issues(quote, QUOTE_REQUIRED_FIELDS, key),
            *self._record_status_issues(quote, key),
            *self._authorization_issues(quote, key, authorized_providers),
            *self._quote_consistency_issues(quote),
        ]
        source_time = _get_datetime(quote, "source_time")
        if source_time is not None:
            issues.extend(
                self._freshness_issues(
                    source_time,
                    as_of,
                    self.policy.quote_stale_after,
                    key=key,
                )
            )
        return issues

    def _bar_required_field_issues(self, bars: Sequence[Bar]) -> list[DataQualityIssue]:
        issues: list[DataQualityIssue] = []
        for bar in bars:
            issues.extend(
                self._required_field_issues(bar, BAR_REQUIRED_FIELDS, _bar_record_key(bar))
            )
        return issues

    def _bar_uniqueness_issues(self, bars: Sequence[Bar]) -> list[DataQualityIssue]:
        issues: list[DataQualityIssue] = []
        seen: set[tuple[Any, Any, Any, Any]] = set()
        for bar in bars:
            key = (
                _get_value(bar, "security_id"),
                _get_value(bar, "interval"),
                _get_value(bar, "adjustment"),
                _get_value(bar, "start_time"),
            )
            if key in seen:
                issues.append(
                    _issue(
                        code="DQ-01-DUPLICATE-BAR",
                        check=DataQualityCheck.UNIQUENESS,
                        message="Duplicate bar for security, interval, adjustment, and timestamp.",
                        record_key=_bar_record_key(bar),
                    )
                )
            seen.add(key)
        return issues

    def _bar_completeness_issues(
        self,
        bars: Sequence[Bar],
        request: BarsRequest | None,
    ) -> list[DataQualityIssue]:
        if request is None:
            return []

        expected = expected_bar_windows(request)
        if not expected:
            return []

        present_starts = {
            bar.start_time
            for bar in bars
            if _get_value(bar, "security_id") == request.security_id
            and _get_value(bar, "interval") == request.interval
            and _get_value(bar, "adjustment") == request.adjustment
        }
        missing = [
            window_start
            for window_start, _window_end in expected
            if window_start not in present_starts
        ]
        if not missing:
            return []

        return [
            _issue(
                code="DQ-04-MISSING-BARS",
                check=DataQualityCheck.COMPLETENESS,
                message=f"Missing {len(missing)} expected bar(s) in requested window.",
                record_key=f"{request.security_id}|{request.interval.value}",
            )
        ]

    def _quote_consistency_issues(self, quote: Quote) -> list[DataQualityIssue]:
        latest_price = _get_number(quote, "latest_price")
        open_price = _get_number(quote, "open_price")
        high_price = _get_number(quote, "high_price")
        low_price = _get_number(quote, "low_price")
        if latest_price is None or open_price is None or high_price is None or low_price is None:
            return []
        if high_price < max(open_price, latest_price) or low_price > min(open_price, latest_price):
            return [
                _issue(
                    code="DQ-03-QUOTE-OHLC",
                    check=DataQualityCheck.CONSISTENCY,
                    message="Quote high/low does not contain open and latest prices.",
                    record_key=_quote_record_key(quote),
                )
            ]
        return []

    def _bar_consistency_issues(self, bar: Bar) -> list[DataQualityIssue]:
        open_price = _get_number(bar, "open_price")
        high_price = _get_number(bar, "high_price")
        low_price = _get_number(bar, "low_price")
        close_price = _get_number(bar, "close_price")
        if open_price is None or high_price is None or low_price is None or close_price is None:
            return []
        if high_price < max(open_price, close_price) or low_price > min(open_price, close_price):
            return [
                _issue(
                    code="DQ-03-BAR-OHLC",
                    check=DataQualityCheck.CONSISTENCY,
                    message="Bar high/low does not contain open and close prices.",
                    record_key=_bar_record_key(bar),
                )
            ]
        return []

    def _source_chronology_issues(
        self,
        source_times: Sequence[tuple[datetime, datetime, str]],
    ) -> list[DataQualityIssue]:
        issues: list[DataQualityIssue] = []
        previous_source_time: datetime | None = None
        for _start_time, source_time, key in sorted(source_times, key=lambda item: item[0]):
            if previous_source_time is not None and source_time < previous_source_time:
                issues.append(
                    _issue(
                        code="DQ-02-SOURCE-REVERSED",
                        check=DataQualityCheck.SOURCE_CHRONOLOGY,
                        message="Provider source_time moved backwards across ordered records.",
                        record_key=key,
                    )
                )
            previous_source_time = source_time
        return issues

    def _freshness_issues(
        self,
        source_time: datetime,
        as_of: datetime,
        stale_after: timedelta,
        *,
        key: str,
    ) -> list[DataQualityIssue]:
        if as_of - source_time <= stale_after:
            return []
        return [
            _issue(
                code="DQ-02-STALE",
                check=DataQualityCheck.FRESHNESS,
                message=(
                    "Source data age "
                    f"{(as_of - source_time).total_seconds():.0f}s exceeds threshold."
                ),
                record_key=key,
            )
        ]

    def _record_status_issues(self, record: Any, key: str) -> list[DataQualityIssue]:
        quality_status = _get_value(record, "quality_status")
        match quality_status:
            case RecordQualityStatus.UNAUTHORIZED:
                return [
                    _issue(
                        code="DQ-AUTH-STATUS",
                        check=DataQualityCheck.AUTHORIZATION,
                        message="Record quality_status is UNAUTHORIZED.",
                        record_key=key,
                    )
                ]
            case RecordQualityStatus.INVALID:
                return [
                    _issue(
                        code="DQ-STATUS-INVALID",
                        check=DataQualityCheck.CONSISTENCY,
                        message="Record quality_status is INVALID.",
                        record_key=key,
                    )
                ]
            case RecordQualityStatus.STALE:
                return [
                    _issue(
                        code="DQ-02-STATUS-STALE",
                        check=DataQualityCheck.FRESHNESS,
                        message="Record quality_status is STALE.",
                        record_key=key,
                    )
                ]
            case RecordQualityStatus.DEGRADED:
                return [
                    _issue(
                        code="DQ-STATUS-DEGRADED",
                        check=DataQualityCheck.CONSISTENCY,
                        severity=DataQualitySeverity.WARNING,
                        message="Record quality_status is DEGRADED.",
                        blocks_signal=False,
                        record_key=key,
                    )
                ]
            case _:
                return []

    def _authorization_issues(
        self,
        record: Any,
        key: str,
        authorized_providers: Collection[str] | None,
    ) -> list[DataQualityIssue]:
        authorized = authorized_providers or self.policy.authorized_providers
        if authorized is None:
            return []

        provider = _get_value(record, "provider")
        if provider in authorized:
            return []
        return [
            _issue(
                code="DQ-AUTH-PROVIDER",
                check=DataQualityCheck.AUTHORIZATION,
                message="Record provider is not in the authorized provider set.",
                record_key=key,
            )
        ]

    def _required_field_issues(
        self,
        record: Any,
        fields: Sequence[str],
        key: str,
    ) -> list[DataQualityIssue]:
        issues: list[DataQualityIssue] = []
        for field in fields:
            value = _get_value(record, field)
            if value is None or value == "":
                issues.append(
                    _issue(
                        code="DQ-MISSING-FIELD",
                        check=DataQualityCheck.REQUIRED_FIELDS,
                        message=f"Required field {field!r} is missing.",
                        record_key=key,
                    )
                )
        return issues

    def _report(
        self,
        as_of: datetime,
        issues: Sequence[DataQualityIssue],
    ) -> DataQualityReport:
        issue_tuple = tuple(issues)
        blocking_issues = [issue for issue in issue_tuple if issue.blocks_signal]
        health = DataHealth(
            status=_health_status(issue_tuple),
            block_signal=bool(blocking_issues),
            as_of=as_of,
            issues=tuple(f"{issue.code}: {issue.message}" for issue in issue_tuple),
        )
        return DataQualityReport(as_of=as_of, health=health, issues=issue_tuple)


QUOTE_REQUIRED_FIELDS = (
    "security_id",
    "latest_price",
    "previous_close",
    "open_price",
    "high_price",
    "low_price",
    "volume",
    "amount",
    "provider",
    "schema_version",
    "source_time",
    "observed_at",
    "received_at",
    "quality_status",
)

BAR_REQUIRED_FIELDS = (
    "security_id",
    "interval",
    "start_time",
    "end_time",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "amount",
    "adjustment",
    "provider",
    "schema_version",
    "source_time",
    "observed_at",
    "received_at",
    "quality_status",
)


def _issue(
    *,
    code: str,
    check: DataQualityCheck,
    message: str,
    severity: DataQualitySeverity = DataQualitySeverity.BLOCKING,
    blocks_signal: bool = True,
    record_key: str | None = None,
) -> DataQualityIssue:
    return DataQualityIssue(
        code=code,
        check=check,
        severity=severity,
        message=message,
        blocks_signal=blocks_signal,
        record_key=record_key,
    )


def _health_status(issues: Sequence[DataQualityIssue]) -> DataHealthStatus:
    if not issues:
        return DataHealthStatus.HEALTHY
    if any(
        issue.check is DataQualityCheck.AUTHORIZATION and issue.blocks_signal for issue in issues
    ):
        return DataHealthStatus.UNAUTHORIZED
    if any(
        issue.check
        in {
            DataQualityCheck.UNIQUENESS,
            DataQualityCheck.COMPLETENESS,
            DataQualityCheck.CONSISTENCY,
            DataQualityCheck.REQUIRED_FIELDS,
            DataQualityCheck.SOURCE_CHRONOLOGY,
        }
        and issue.blocks_signal
        for issue in issues
    ):
        return DataHealthStatus.INVALID
    if any(issue.check is DataQualityCheck.FRESHNESS and issue.blocks_signal for issue in issues):
        return DataHealthStatus.STALE
    return DataHealthStatus.DEGRADED


def _quote_record_key(quote: Quote) -> str:
    return f"{_get_value(quote, 'security_id')}|{_get_value(quote, 'source_time')}"


def _bar_record_key(bar: Bar) -> str:
    security_id = _get_value(bar, "security_id")
    interval = _get_value(bar, "interval")
    start_time = _get_value(bar, "start_time")
    return f"{security_id}|{interval}|{start_time}"


def _get_value(record: Any, field: str) -> Any:
    return getattr(record, field, None)


def _get_datetime(record: Any, field: str) -> datetime | None:
    value = _get_value(record, field)
    return value if isinstance(value, datetime) else None


def _get_number(record: Any, field: str) -> float | None:
    value = _get_value(record, field)
    return float(value) if isinstance(value, int | float) else None


__all__ = [
    "DataQualityCheck",
    "DataQualityIssue",
    "DataQualityPolicy",
    "DataQualityReport",
    "DataQualityService",
    "DataQualitySeverity",
]
