"""Factor metadata and registry tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from china_quant_platform.factors import (
    FactorCategory,
    FactorDefinition,
    FactorDirection,
    FactorMetadata,
    FactorRegistry,
    FactorVisibility,
    default_factor_registry,
)


def test_factor_metadata_requires_versioned_namespace() -> None:
    with pytest.raises(ValidationError):
        FactorMetadata(
            name="momentum.ret_20d",
            version="v1",
            category=FactorCategory.MOMENTUM,
            direction=FactorDirection.HIGHER_IS_BETTER,
            visible_at=FactorVisibility.SAME_BAR_CLOSE,
            lookback=20,
            description="20 bar return.",
            expected_meaning="Higher values indicate stronger momentum.",
            source="close prices",
        )


def test_default_factor_registry_contains_expected_metadata() -> None:
    registry = default_factor_registry()

    metadata = registry.list_metadata()
    names = tuple(item.name for item in metadata)

    assert names == tuple(sorted(names))
    assert "momentum.ret_20d.v1" in names
    assert "risk.volatility_20d.v1" in names
    assert "risk.drawdown_from_peak.v1" in names
    assert "momentum.relative_strength_20d.v1" in names
    assert registry.get("momentum.ret_20d.v1").metadata.lookback == 20


def test_factor_registry_rejects_duplicates() -> None:
    metadata = FactorMetadata(
        name="momentum.demo.v1",
        version="v1",
        category=FactorCategory.MOMENTUM,
        direction=FactorDirection.HIGHER_IS_BETTER,
        visible_at=FactorVisibility.SAME_BAR_CLOSE,
        lookback=1,
        description="Demo factor.",
        expected_meaning="Higher demo values are better.",
        source="fixture",
    )
    definition = FactorDefinition(metadata=metadata, compute=lambda inputs: (1.0,))
    registry = FactorRegistry((definition,))

    with pytest.raises(ValueError):
        registry.register(definition)


def test_default_factor_computations_are_point_in_time() -> None:
    registry = default_factor_registry()
    close = tuple(float(100 + index) for index in range(21))
    benchmark = tuple(float(100 + index / 2) for index in range(21))

    returns_factor = registry.compute("momentum.ret_20d.v1", {"close": close})
    drawdown_factor = registry.compute("risk.drawdown_from_peak.v1", {"close": close})
    relative_strength_factor = registry.compute(
        "momentum.relative_strength_20d.v1",
        {"close": close, "benchmark_close": benchmark},
    )

    assert returns_factor[:-1] == (None,) * 20
    assert returns_factor[-1] == pytest.approx(0.2)
    assert drawdown_factor == (0.0,) * 21
    assert relative_strength_factor[-1] == pytest.approx(0.2 - 0.1)


def test_factor_cache_key_is_order_independent() -> None:
    registry = default_factor_registry()

    key_a = registry.cache_key(
        "momentum.ret_20d.v1",
        security_id="SSE:600519",
        interval="1d",
        data_snapshot_id="snapshot-001",
        parameters={"periods": 20, "winsorize": False},
        input_fingerprint="abc",
    )
    key_b = registry.cache_key(
        "momentum.ret_20d.v1",
        security_id="SSE:600519",
        interval="1d",
        data_snapshot_id="snapshot-001",
        parameters={"winsorize": False, "periods": 20},
        input_fingerprint="abc",
    )

    assert key_a == key_b
    assert key_a.startswith("momentum.ret_20d.v1:")
