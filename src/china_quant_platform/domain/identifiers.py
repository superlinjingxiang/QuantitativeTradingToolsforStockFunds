"""Typed aliases for stable domain identifiers."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

type NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

type SecurityId = NonEmptyString
type ProviderId = NonEmptyString
type SchemaVersion = NonEmptyString
type StrategyId = NonEmptyString
type ModelVersion = NonEmptyString
type RuleVersion = NonEmptyString
type DataSnapshotId = NonEmptyString
type RuleId = NonEmptyString
