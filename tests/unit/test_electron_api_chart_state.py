"""Contract tests for the Vue chart backtest mode."""

from china_quant_platform.electron_api import (
    _overlays_from_payload,
    _synchronize_backtest_overlay,
)
from china_quant_platform.ui.state import ChartOverlay


def test_chart_backtest_mode_owns_the_signal_overlay() -> None:
    normal = _overlays_from_payload(["VOLUME"])
    active = _synchronize_backtest_overlay(normal, active=True)
    assert active == frozenset({ChartOverlay.VOLUME, ChartOverlay.SIGNALS})

    restored = _synchronize_backtest_overlay(active, active=False)
    assert restored == frozenset({ChartOverlay.VOLUME})
