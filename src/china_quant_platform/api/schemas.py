"""Permissive request models preserving the existing JSON API contract."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    query: str | None = None
    securityId: str | None = None
    strategyMode: str | None = None
    maxTrades: int | None = Field(default=None, ge=1, le=60)
    interval: str | None = None
    range: str | None = None
    adjustment: str | None = None
    overlays: list[str] | None = None
    chartBacktestActive: bool | None = None
    accountContext: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class RecommendationPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    limit: int = Field(default=10, ge=1, le=30)
    horizonDays: int = Field(default=10, ge=1, le=21)
    includeUsLinked: bool = True

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)
