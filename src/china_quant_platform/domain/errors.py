"""Typed domain errors exposed across application and UI boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DomainErrorKind(StrEnum):
    DATA_UNAVAILABLE = "DataUnavailable"
    DATA_STALE = "DataStale"
    DATA_INVALID = "DataInvalid"
    UNAUTHORIZED_DATA = "UnauthorizedData"
    RULE_MISSING = "RuleMissing"
    INSUFFICIENT_HISTORY = "InsufficientHistory"
    MODEL_OUT_OF_DISTRIBUTION = "ModelOutOfDistribution"
    PROVIDER_RATE_LIMIT = "ProviderRateLimit"
    CANCELLED = "Cancelled"
    INTERNAL_ERROR = "InternalError"


@dataclass(frozen=True, slots=True)
class DomainError(Exception):
    """A typed, UI-safe domain error."""

    kind: DomainErrorKind
    user_message: str
    engineering_message: str
    code: str
    retryable: bool
    blocks_signal: bool

    def __str__(self) -> str:
        return f"{self.kind.value}({self.code}): {self.user_message}"

    def to_problem_dict(self) -> dict[str, str | bool]:
        return {
            "kind": self.kind.value,
            "code": self.code,
            "user_message": self.user_message,
            "engineering_message": self.engineering_message,
            "retryable": self.retryable,
            "blocks_signal": self.blocks_signal,
        }


class DataUnavailable(DomainError):
    def __init__(self, engineering_message: str, *, retryable: bool = True) -> None:
        super().__init__(
            kind=DomainErrorKind.DATA_UNAVAILABLE,
            user_message="Data is unavailable for the requested security or interval.",
            engineering_message=engineering_message,
            code="DATA_UNAVAILABLE",
            retryable=retryable,
            blocks_signal=True,
        )


class DataStale(DomainError):
    def __init__(self, engineering_message: str) -> None:
        super().__init__(
            kind=DomainErrorKind.DATA_STALE,
            user_message="Data is stale. New trading signals are paused.",
            engineering_message=engineering_message,
            code="DATA_STALE",
            retryable=True,
            blocks_signal=True,
        )


class DataInvalid(DomainError):
    def __init__(self, engineering_message: str) -> None:
        super().__init__(
            kind=DomainErrorKind.DATA_INVALID,
            user_message="Data failed validation. New trading signals are blocked.",
            engineering_message=engineering_message,
            code="DATA_INVALID",
            retryable=False,
            blocks_signal=True,
        )


class UnauthorizedData(DomainError):
    def __init__(self, engineering_message: str) -> None:
        super().__init__(
            kind=DomainErrorKind.UNAUTHORIZED_DATA,
            user_message="Data is not authorized for this use.",
            engineering_message=engineering_message,
            code="UNAUTHORIZED_DATA",
            retryable=False,
            blocks_signal=True,
        )


class RuleMissing(DomainError):
    def __init__(self, engineering_message: str) -> None:
        super().__init__(
            kind=DomainErrorKind.RULE_MISSING,
            user_message="Required market rules are missing for this date and security.",
            engineering_message=engineering_message,
            code="RULE_MISSING",
            retryable=False,
            blocks_signal=True,
        )


class InsufficientHistory(DomainError):
    def __init__(self, engineering_message: str) -> None:
        super().__init__(
            kind=DomainErrorKind.INSUFFICIENT_HISTORY,
            user_message="There is not enough history to evaluate this model or indicator.",
            engineering_message=engineering_message,
            code="INSUFFICIENT_HISTORY",
            retryable=True,
            blocks_signal=True,
        )


class ModelOutOfDistribution(DomainError):
    def __init__(self, engineering_message: str) -> None:
        super().__init__(
            kind=DomainErrorKind.MODEL_OUT_OF_DISTRIBUTION,
            user_message="Model inputs are outside the validated distribution.",
            engineering_message=engineering_message,
            code="MODEL_OUT_OF_DISTRIBUTION",
            retryable=False,
            blocks_signal=True,
        )


class ProviderRateLimit(DomainError):
    def __init__(self, engineering_message: str) -> None:
        super().__init__(
            kind=DomainErrorKind.PROVIDER_RATE_LIMIT,
            user_message="The data provider rate limit was reached.",
            engineering_message=engineering_message,
            code="PROVIDER_RATE_LIMIT",
            retryable=True,
            blocks_signal=False,
        )


class Cancelled(DomainError):
    def __init__(self, engineering_message: str = "Operation was cancelled.") -> None:
        super().__init__(
            kind=DomainErrorKind.CANCELLED,
            user_message="The operation was cancelled.",
            engineering_message=engineering_message,
            code="CANCELLED",
            retryable=False,
            blocks_signal=False,
        )


class InternalError(DomainError):
    def __init__(self, engineering_message: str) -> None:
        super().__init__(
            kind=DomainErrorKind.INTERNAL_ERROR,
            user_message="An internal error occurred.",
            engineering_message=engineering_message,
            code="INTERNAL_ERROR",
            retryable=True,
            blocks_signal=True,
        )
