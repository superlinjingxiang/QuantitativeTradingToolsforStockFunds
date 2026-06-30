"""Local security master and fuzzy search index."""

from __future__ import annotations

from datetime import date
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from china_quant_platform.domain import SecurityRef, SecurityStatus
from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import NonEmptyString, SecurityId


class SecurityMasterRecord(DomainModel):
    """Point-in-time snapshots for one stable security identity."""

    security_id: SecurityId
    snapshots: tuple[SecurityRef, ...]

    @model_validator(mode="after")
    def snapshots_must_belong_to_security_and_have_unique_dates(self) -> Self:
        if not self.snapshots:
            raise ValueError("snapshots must not be empty")

        status_dates: set[date] = set()
        for snapshot in self.snapshots:
            if snapshot.security_id != self.security_id:
                raise ValueError("all snapshots must share security_id")
            if snapshot.status_date in status_dates:
                raise ValueError("snapshot status_date values must be unique")
            status_dates.add(snapshot.status_date)
        return self

    @property
    def latest_snapshot(self) -> SecurityRef:
        return max(self.snapshots, key=lambda snapshot: snapshot.status_date)

    def security_at(self, as_of: date) -> SecurityRef | None:
        eligible = [
            snapshot
            for snapshot in self.snapshots
            if snapshot.listed_date <= as_of and snapshot.status_date <= as_of
        ]
        if not eligible:
            return None
        return max(eligible, key=lambda snapshot: snapshot.status_date)


class SecuritySearchResult(DomainModel):
    query: NonEmptyString
    security: SecurityRef
    score: float = Field(ge=0, le=1)
    matched_fields: tuple[NonEmptyString, ...]


class RecentSecuritySelection(DomainModel):
    security_id: SecurityId
    selected_at: AwareDatetime


class SecurityMasterService:
    """In-memory local search service for standard securities."""

    def __init__(
        self,
        records: list[SecurityMasterRecord] | tuple[SecurityMasterRecord, ...],
        *,
        recent_limit: int = 20,
    ) -> None:
        if recent_limit < 1:
            raise ValueError("recent_limit must be positive")
        self._records = {record.security_id: record for record in records}
        if len(self._records) != len(records):
            raise ValueError("security_id values must be unique")
        self._recent_limit = recent_limit
        self._recent: list[RecentSecuritySelection] = []

    @classmethod
    def from_securities(
        cls,
        securities: list[SecurityRef] | tuple[SecurityRef, ...],
        *,
        recent_limit: int = 20,
    ) -> Self:
        grouped: dict[str, list[SecurityRef]] = {}
        for security in securities:
            grouped.setdefault(security.security_id, []).append(security)

        records = [
            SecurityMasterRecord(
                security_id=security_id,
                snapshots=tuple(sorted(snapshots, key=lambda snapshot: snapshot.status_date)),
            )
            for security_id, snapshots in grouped.items()
        ]
        return cls(records, recent_limit=recent_limit)

    def get_security(self, security_id: str, *, as_of: date | None = None) -> SecurityRef | None:
        record = self._records.get(security_id)
        if record is None:
            return None
        if as_of is None:
            return record.latest_snapshot
        return record.security_at(as_of)

    def select_security(
        self,
        security_id: str,
        *,
        selected_at: AwareDatetime,
        as_of: date | None = None,
    ) -> SecurityRef:
        security = self.get_security(security_id, as_of=as_of)
        if security is None:
            raise KeyError(f"Unknown or unavailable security_id: {security_id}")

        self.record_recent(security.security_id, selected_at=selected_at)
        return security

    def search(
        self,
        query: str,
        *,
        as_of: date | None = None,
        limit: int = 10,
        include_inactive: bool = True,
    ) -> list[SecuritySearchResult]:
        normalized_query = _normalize(query)
        stripped_query = query.strip()
        if not normalized_query or not stripped_query or limit < 1:
            return []

        results: list[SecuritySearchResult] = []
        for record in self._records.values():
            security = record.latest_snapshot if as_of is None else record.security_at(as_of)
            if security is None:
                continue
            if not include_inactive and security.status is not SecurityStatus.ACTIVE:
                continue

            score, matched_fields = _score_security(normalized_query, security)
            if score > 0 and matched_fields:
                results.append(
                    SecuritySearchResult(
                        query=stripped_query,
                        security=security,
                        score=score,
                        matched_fields=matched_fields,
                    )
                )

        return sorted(
            results,
            key=lambda result: (
                -result.score,
                result.security.status is not SecurityStatus.ACTIVE,
                result.security.security_id,
            ),
        )[:limit]

    def record_recent(self, security_id: str, *, selected_at: AwareDatetime) -> None:
        if security_id not in self._records:
            raise KeyError(f"Unknown security_id: {security_id}")
        self._recent = [entry for entry in self._recent if entry.security_id != security_id]
        self._recent.insert(
            0,
            RecentSecuritySelection(security_id=security_id, selected_at=selected_at),
        )
        del self._recent[self._recent_limit :]

    def upsert_security(self, security: SecurityRef) -> None:
        record = self._records.get(security.security_id)
        if record is None:
            self._records[security.security_id] = SecurityMasterRecord(
                security_id=security.security_id,
                snapshots=(security,),
            )
            return

        snapshots_by_date = {snapshot.status_date: snapshot for snapshot in record.snapshots}
        snapshots_by_date[security.status_date] = security
        self._records[security.security_id] = SecurityMasterRecord(
            security_id=security.security_id,
            snapshots=tuple(sorted(snapshots_by_date.values(), key=lambda item: item.status_date)),
        )

    def recent_searches(
        self,
        *,
        as_of: date | None = None,
        limit: int | None = None,
    ) -> list[SecurityRef]:
        if limit is not None and limit < 1:
            return []

        securities: list[SecurityRef] = []
        for entry in self._recent:
            security = self.get_security(entry.security_id, as_of=as_of)
            if security is not None:
                securities.append(security)
            if limit is not None and len(securities) >= limit:
                break
        return securities

    def all_security_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._records))


def _score_security(normalized_query: str, security: SecurityRef) -> tuple[float, tuple[str, ...]]:
    candidates = (
        ("security_id", security.security_id, 1.0, 0.9, 0.78, 0.6),
        ("symbol", security.symbol, 1.0, 0.92, 0.8, 0.62),
        ("name", security.name, 0.95, 0.86, 0.72, 0.55),
        *(
            (f"alias:{index}", alias, 0.9, 0.82, 0.68, 0.52)
            for index, alias in enumerate(security.aliases)
        ),
    )

    best_score = 0.0
    matched_fields: list[str] = []
    for field_name, value, exact_score, prefix_score, contains_score, fuzzy_score in candidates:
        candidate = _normalize(value)
        score = _score_candidate(
            normalized_query,
            candidate,
            exact_score=exact_score,
            prefix_score=prefix_score,
            contains_score=contains_score,
            fuzzy_score=fuzzy_score,
        )
        if score > best_score:
            best_score = score
            matched_fields = [field_name]
        elif score > 0 and score == best_score:
            matched_fields.append(field_name)

    return best_score, tuple(matched_fields)


def _score_candidate(
    query: str,
    candidate: str,
    *,
    exact_score: float,
    prefix_score: float,
    contains_score: float,
    fuzzy_score: float,
) -> float:
    if not candidate:
        return 0.0
    if query == candidate:
        return exact_score
    if candidate.startswith(query):
        return prefix_score
    if query in candidate:
        return contains_score
    if _is_subsequence(query, candidate):
        return fuzzy_score * min(len(query) / len(candidate), 1.0)
    return 0.0


def _normalize(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _is_subsequence(query: str, candidate: str) -> bool:
    if not query:
        return False

    index = 0
    for character in candidate:
        if character == query[index]:
            index += 1
            if index == len(query):
                return True
    return False
