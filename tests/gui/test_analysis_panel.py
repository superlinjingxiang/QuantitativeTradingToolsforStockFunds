"""GUI analysis panel tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from PySide6 import QtWidgets

from china_quant_platform.domain import (
    AbstainReason,
    AnalysisReport,
    DataHealth,
    DataHealthStatus,
    DirectionProbabilities,
    FinalSignal,
)
from china_quant_platform.ui import ApplicationViewModel, MainWindow, UiRunState


def as_of() -> datetime:
    return datetime(2026, 6, 29, 15, 0, tzinfo=UTC)


def data_health(
    status: DataHealthStatus = DataHealthStatus.HEALTHY,
    *,
    block_signal: bool = False,
    issues: tuple[str, ...] = (),
) -> DataHealth:
    return DataHealth(status=status, block_signal=block_signal, as_of=as_of(), issues=issues)


def report(
    *,
    final_signal: FinalSignal = FinalSignal.BUY_CANDIDATE,
    abstain_reason: AbstainReason | None = None,
    health: DataHealth | None = None,
    probabilities: DirectionProbabilities | None = None,
) -> AnalysisReport:
    return AnalysisReport(
        security_id="SSE:600519",
        as_of=as_of(),
        data_health=health or data_health(),
        strategy_id="strategy.demo",
        strategy_version="v1",
        horizon=5,
        market_regime="RANGE_STRONG",
        direction_probabilities=probabilities
        or DirectionProbabilities(up=0.62, flat=0.23, down=0.15),
        raw_signal="BUY_BIAS",
        final_signal=final_signal,
        valid_until=as_of() + timedelta(days=1),
        positive_drivers=("momentum.ret_20d.v1=0.08: Momentum supports candidate.",),
        negative_drivers=("risk.volatility_20d.v1=0.18: Volatility reduces conviction.",),
        model_version="forecast-model-v1",
        rule_version="rules-cn-v1",
        data_snapshot_id="snapshot-020",
        expected_return_quantiles={"p05": -0.02, "p50": 0.03, "p95": 0.09},
        expected_drawdown=-0.04,
        grade="B",
        target_position_limit=0.05,
        exit_or_invalidation_conditions=("trend_breaks: trend support fails.",),
        abstain_reason=abstain_reason,
    )


def test_view_model_applies_analysis_report_to_panel_state() -> None:
    view_model = ApplicationViewModel(clock=as_of)
    view_model.select_security("SSE:600519")

    view_model.apply_analysis_report(
        report(),
        generation=view_model.state.selection_generation,
        strategy_name="Demo momentum strategy",
        strategy_summary="Calibrated sample status.",
        applicable_conditions=("trend_confirmed: trend is visible.",),
    )

    assert view_model.state.run_state is UiRunState.REALTIME_RUNNING
    assert view_model.state.analysis.strategy.strategy_name == "Demo momentum strategy"
    assert view_model.state.analysis.forecast.direction_label == "震荡上涨"
    assert "上涨62.0%" in view_model.state.analysis.forecast.probability_summary
    assert view_model.state.analysis.operation.final_signal == "BUY_CANDIDATE"
    assert view_model.state.analysis.operation.target_position_limit == "5.0%"


def test_main_window_renders_strategy_forecast_and_operation_panels(qtbot: Any) -> None:
    view_model = ApplicationViewModel(clock=as_of)
    window = MainWindow(view_model)
    qtbot.addWidget(window)
    view_model.select_security("SSE:600519")

    view_model.apply_analysis_report(
        report(),
        generation=view_model.state.selection_generation,
        strategy_name="Demo momentum strategy",
        strategy_summary="Calibrated sample status.",
        applicable_conditions=("trend_confirmed: trend is visible.",),
    )

    strategy_label = window.findChild(QtWidgets.QLabel, "strategyPanelText")
    forecast_label = window.findChild(QtWidgets.QLabel, "forecastPanelText")
    operation_label = window.findChild(QtWidgets.QLabel, "operationPanelText")
    assert strategy_label is not None
    assert forecast_label is not None
    assert operation_label is not None
    assert "Demo momentum strategy" in strategy_label.text()
    assert "rules-cn-v1" in strategy_label.text()
    assert "上涨62.0%" in forecast_label.text()
    assert "预测区间" in forecast_label.text()
    assert "BUY_CANDIDATE" in operation_label.text()
    assert "trend_breaks" in operation_label.text()


def test_stale_data_report_is_visible_as_abstain_in_gui(qtbot: Any) -> None:
    view_model = ApplicationViewModel(clock=as_of)
    window = MainWindow(view_model)
    qtbot.addWidget(window)
    view_model.select_security("SSE:600519")
    stale_report = report(
        final_signal=FinalSignal.ABSTAIN,
        abstain_reason=AbstainReason.DATA,
        health=data_health(
            DataHealthStatus.STALE,
            block_signal=True,
            issues=("stale quote",),
        ),
    )

    view_model.apply_analysis_report(
        stale_report,
        generation=view_model.state.selection_generation,
    )

    operation_label = window.findChild(QtWidgets.QLabel, "operationPanelText")
    assert operation_label is not None
    assert view_model.state.run_state is UiRunState.DATA_STALE
    assert "ABSTAIN" in operation_label.text()
    assert "DATA" in operation_label.text()
    assert "stale quote" in operation_label.text()
    assert window.health_banner.property("blocked") is True


def test_model_uncertainty_report_sets_ood_state_and_ignores_old_generation() -> None:
    view_model = ApplicationViewModel(clock=as_of)
    view_model.select_security("SSE:600519")
    old_generation = view_model.state.selection_generation
    view_model.select_security("SSE:510300")
    model_abstain_report = report(
        final_signal=FinalSignal.ABSTAIN,
        abstain_reason=AbstainReason.MODEL_UNCERTAINTY,
    )

    view_model.apply_analysis_report(model_abstain_report, generation=old_generation)
    assert view_model.state.analysis.report is None

    view_model.select_security("SSE:600519")
    view_model.apply_analysis_report(
        model_abstain_report,
        generation=view_model.state.selection_generation,
    )

    assert view_model.state.run_state is UiRunState.MODEL_OUT_OF_DISTRIBUTION
    assert view_model.state.analysis.operation.abstain_reason == "MODEL_UNCERTAINTY"
