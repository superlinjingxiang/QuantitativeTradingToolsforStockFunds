"""Versioned factor metadata and registry for deterministic research pipelines."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from china_quant_platform.domain.base import DomainModel
from china_quant_platform.domain.identifiers import NonEmptyString
from china_quant_platform.indicators import (
    IndicatorValue,
    drawdown,
    relative_strength,
    returns,
    rolling_volatility,
    stable_cache_digest,
)

type FactorInput = Mapping[str, Sequence[float | int | None]]
type FactorCompute = Callable[[FactorInput], tuple[IndicatorValue, ...]]
type FactorParameter = str | int | float | bool | None


class FactorCategory(StrEnum):
    MOMENTUM = "MOMENTUM"
    RISK = "RISK"
    LIQUIDITY = "LIQUIDITY"
    QUALITY = "QUALITY"
    VALUE = "VALUE"
    MARKET_STATE = "MARKET_STATE"


class FactorDirection(StrEnum):
    HIGHER_IS_BETTER = "HIGHER_IS_BETTER"
    LOWER_IS_BETTER = "LOWER_IS_BETTER"
    NON_MONOTONIC = "NON_MONOTONIC"


class FactorVisibility(StrEnum):
    SAME_BAR_CLOSE = "SAME_BAR_CLOSE"
    NEXT_BAR_OPEN = "NEXT_BAR_OPEN"
    ANNOUNCEMENT_TIME = "ANNOUNCEMENT_TIME"


class FactorMetadata(DomainModel):
    """Auditable metadata required before a factor can enter a strategy."""

    name: NonEmptyString
    version: NonEmptyString
    category: FactorCategory
    direction: FactorDirection
    visible_at: FactorVisibility
    lookback: int = Field(ge=1)
    description: NonEmptyString
    expected_meaning: NonEmptyString
    source: NonEmptyString
    parameters: dict[str, FactorParameter] = Field(default_factory=dict)
    preprocessing: tuple[NonEmptyString, ...] = ()
    invalidation_conditions: tuple[NonEmptyString, ...] = ()

    @model_validator(mode="after")
    def name_must_include_matching_version(self) -> Self:
        if not self.name.endswith(f".{self.version}"):
            raise ValueError("factor name must end with its version, for example namespace.name.v1")
        if self.name.count(".") < 2:
            raise ValueError("factor name must include namespace, short name, and version")
        return self


@dataclass(frozen=True, slots=True)
class FactorDefinition:
    metadata: FactorMetadata
    compute: FactorCompute


class FactorRegistry:
    """In-memory factor registry with deterministic metadata ordering."""

    def __init__(self, definitions: Sequence[FactorDefinition] = ()) -> None:
        self._definitions: dict[str, FactorDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: FactorDefinition) -> None:
        name = definition.metadata.name
        if name in self._definitions:
            raise ValueError(f"factor already registered: {name}")
        self._definitions[name] = definition

    def get(self, name: str) -> FactorDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise KeyError(f"factor is not registered: {name}") from exc

    def list_metadata(self) -> tuple[FactorMetadata, ...]:
        return tuple(self._definitions[name].metadata for name in sorted(self._definitions))

    def compute(self, name: str, inputs: FactorInput) -> tuple[IndicatorValue, ...]:
        return self.get(name).compute(inputs)

    def cache_key(
        self,
        name: str,
        *,
        security_id: str,
        interval: str,
        data_snapshot_id: str,
        parameters: Mapping[str, FactorParameter] | None = None,
        input_fingerprint: str = "unspecified",
    ) -> str:
        metadata = self.get(name).metadata
        payload = {
            "name": metadata.name,
            "version": metadata.version,
            "security_id": security_id,
            "interval": interval,
            "data_snapshot_id": data_snapshot_id,
            "parameters": dict(parameters or metadata.parameters),
            "input_fingerprint": input_fingerprint,
        }
        return f"{metadata.name}:{stable_cache_digest('factor', payload)}"


def default_factor_registry() -> FactorRegistry:
    return FactorRegistry(
        (
            FactorDefinition(
                metadata=FactorMetadata(
                    name="momentum.ret_20d.v1",
                    version="v1",
                    category=FactorCategory.MOMENTUM,
                    direction=FactorDirection.HIGHER_IS_BETTER,
                    visible_at=FactorVisibility.SAME_BAR_CLOSE,
                    lookback=20,
                    description="20 bar close-to-close return.",
                    expected_meaning="Higher values indicate stronger medium-term momentum.",
                    source="close prices",
                    parameters={"periods": 20},
                    preprocessing=("point_in_time_close", "missing_to_null"),
                    invalidation_conditions=("insufficient_history", "stale_or_invalid_price"),
                ),
                compute=lambda inputs: returns(_require_series(inputs, "close"), periods=20),
            ),
            FactorDefinition(
                metadata=FactorMetadata(
                    name="risk.volatility_20d.v1",
                    version="v1",
                    category=FactorCategory.RISK,
                    direction=FactorDirection.LOWER_IS_BETTER,
                    visible_at=FactorVisibility.SAME_BAR_CLOSE,
                    lookback=21,
                    description="Annualized 20 bar realized volatility from close returns.",
                    expected_meaning="Lower values indicate less realized price variability.",
                    source="close prices",
                    parameters={"window": 20, "annualization": 252},
                    preprocessing=("point_in_time_close", "population_std"),
                    invalidation_conditions=("insufficient_history", "stale_or_invalid_price"),
                ),
                compute=lambda inputs: rolling_volatility(
                    _require_series(inputs, "close"),
                    window=20,
                    annualization=252.0,
                ),
            ),
            FactorDefinition(
                metadata=FactorMetadata(
                    name="risk.drawdown_from_peak.v1",
                    version="v1",
                    category=FactorCategory.RISK,
                    direction=FactorDirection.LOWER_IS_BETTER,
                    visible_at=FactorVisibility.SAME_BAR_CLOSE,
                    lookback=1,
                    description="Current drawdown from the running historical close peak.",
                    expected_meaning="More negative values indicate deeper current drawdown.",
                    source="close prices",
                    preprocessing=("point_in_time_close", "running_peak"),
                    invalidation_conditions=("stale_or_invalid_price",),
                ),
                compute=lambda inputs: drawdown(_require_series(inputs, "close")),
            ),
            FactorDefinition(
                metadata=FactorMetadata(
                    name="momentum.relative_strength_20d.v1",
                    version="v1",
                    category=FactorCategory.MOMENTUM,
                    direction=FactorDirection.HIGHER_IS_BETTER,
                    visible_at=FactorVisibility.SAME_BAR_CLOSE,
                    lookback=20,
                    description="20 bar excess return versus a benchmark close series.",
                    expected_meaning="Higher values indicate outperformance versus benchmark.",
                    source="close and benchmark_close prices",
                    parameters={"window": 20},
                    preprocessing=("point_in_time_close", "benchmark_aligned_by_bar"),
                    invalidation_conditions=("insufficient_history", "benchmark_missing"),
                ),
                compute=lambda inputs: relative_strength(
                    _require_series(inputs, "close"),
                    _require_series(inputs, "benchmark_close"),
                    window=20,
                ),
            ),
        )
    )


def _require_series(inputs: FactorInput, name: str) -> Sequence[float | int | None]:
    try:
        return inputs[name]
    except KeyError as exc:
        raise KeyError(f"factor input is missing required series: {name}") from exc
