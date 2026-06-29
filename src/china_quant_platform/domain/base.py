"""Base model helpers for schema-backed domain contracts."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    """Immutable pydantic model with explicit contract conversion helpers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    @classmethod
    def from_contract_dict(cls, data: dict[str, Any]) -> Self:
        return cls.model_validate(data)

    def to_contract_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
