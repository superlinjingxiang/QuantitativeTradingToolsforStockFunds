"""Typed domain error contract tests."""

from __future__ import annotations

import pytest

from china_quant_platform.domain import (
    Cancelled,
    DataInvalid,
    DataStale,
    DataUnavailable,
    DomainError,
    DomainErrorKind,
    InsufficientHistory,
    InternalError,
    ModelOutOfDistribution,
    ProviderRateLimit,
    RuleMissing,
    UnauthorizedData,
)


@pytest.mark.parametrize(
    ("error", "kind", "blocks_signal"),
    [
        (
            DataUnavailable("provider does not expose 1m bars"),
            DomainErrorKind.DATA_UNAVAILABLE,
            True,
        ),
        (DataStale("quote age exceeded threshold"), DomainErrorKind.DATA_STALE, True),
        (DataInvalid("high is below close"), DomainErrorKind.DATA_INVALID, True),
        (
            UnauthorizedData("missing market data entitlement"),
            DomainErrorKind.UNAUTHORIZED_DATA,
            True,
        ),
        (RuleMissing("no SSE stock rule on date"), DomainErrorKind.RULE_MISSING, True),
        (InsufficientHistory("need 60 bars"), DomainErrorKind.INSUFFICIENT_HISTORY, True),
        (
            ModelOutOfDistribution("feature outside training quantile"),
            DomainErrorKind.MODEL_OUT_OF_DISTRIBUTION,
            True,
        ),
        (ProviderRateLimit("quota exceeded"), DomainErrorKind.PROVIDER_RATE_LIMIT, False),
        (Cancelled(), DomainErrorKind.CANCELLED, False),
        (InternalError("unexpected state"), DomainErrorKind.INTERNAL_ERROR, True),
    ],
)
def test_domain_errors_expose_ui_safe_metadata(
    error: DomainError,
    kind: DomainErrorKind,
    blocks_signal: bool,
) -> None:
    payload = error.to_problem_dict()

    assert error.kind is kind
    assert payload["kind"] == kind.value
    assert payload["code"]
    assert payload["user_message"]
    assert payload["engineering_message"]
    assert payload["blocks_signal"] is blocks_signal
    assert isinstance(payload["retryable"], bool)
