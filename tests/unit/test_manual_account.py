"""Manual account input assessment tests."""

from __future__ import annotations

from china_quant_platform.manual_account import (
    ManualAccountInput,
    evaluate_manual_account,
    manual_account_from_payload,
)


def test_empty_position_buy_candidate_suggests_amount_and_quantity() -> None:
    result = evaluate_manual_account(
        account=ManualAccountInput(planned_capital=10_000, available_cash=10_000),
        latest_price=2.5,
        final_signal="BUY_CANDIDATE",
        grade="B",
        target_position_limit="10.0%",
    )

    assert result["accountAdvice"] == "可小仓试买"
    assert result["suggestedAmount"] == "可操作约1,000.00 元"
    assert result["suggestedQuantity"] == "400 股/份"
    assert result["currentWeight"] == "0.0%"


def test_existing_overweight_position_suggests_reduce() -> None:
    result = evaluate_manual_account(
        account=ManualAccountInput(
            planned_capital=10_000,
            holding_quantity=5_000,
            average_cost=2.0,
        ),
        latest_price=2.2,
        final_signal="HOLD",
        grade="B",
        target_position_limit="20.0%",
    )

    assert result["accountAdvice"] == "建议减仓"
    assert "高于当前策略仓位上限" in result["reason"]
    assert result["suggestedAmount"].startswith("建议减仓约")


def test_watch_signal_does_not_open_new_position() -> None:
    result = evaluate_manual_account(
        account=ManualAccountInput(planned_capital=10_000, available_cash=10_000),
        latest_price=10,
        final_signal="WATCH",
        grade="C",
        target_position_limit="0.0%",
    )

    assert result["accountAdvice"] == "暂不新开仓"
    assert result["suggestedAmount"] == "--"


def test_decision_gate_blocks_new_position_without_erasing_strategy_context() -> None:
    result = evaluate_manual_account(
        account=ManualAccountInput(planned_capital=10_000, available_cash=10_000),
        latest_price=10,
        final_signal="WATCH",
        grade="B",
        target_position_limit=0.0,
        strategy_signal="BUY_CANDIDATE",
        strategy_target_position_limit="10.0%",
        decision_readiness="RESEARCH_ONLY",
    )

    assert result["accountAdvice"] == "暂不新开仓"
    assert result["strategySignal"] == "BUY_CANDIDATE"
    assert result["decisionSignal"] == "WATCH"
    assert result["targetWeight"] == "0.0%"
    assert result["strategyTargetWeight"] == "10.0%"
    assert "最终门禁信号为观察" in result["reason"]


def test_watch_gate_does_not_force_existing_position_to_zero() -> None:
    result = evaluate_manual_account(
        account=ManualAccountInput(
            planned_capital=10_000,
            available_cash=8_000,
            holding_quantity=200,
            average_cost=9.5,
        ),
        latest_price=10,
        final_signal="WATCH",
        grade="B",
        target_position_limit=0.0,
        strategy_signal="HOLD",
        strategy_target_position_limit="25.0%",
        decision_readiness="RESEARCH_ONLY",
    )

    assert result["currentWeight"] == "20.0%"
    assert result["accountAdvice"] == "持有观察"
    assert result["suggestedAmount"] == "--"
    assert "不解释为强制清仓" in result["reason"]


def test_strategy_reduce_survives_watch_gate_for_existing_position() -> None:
    result = evaluate_manual_account(
        account=ManualAccountInput(
            planned_capital=10_000,
            holding_quantity=500,
            average_cost=10,
        ),
        latest_price=10,
        final_signal="WATCH",
        grade="C",
        target_position_limit=0.0,
        strategy_signal="REDUCE",
        strategy_target_position_limit="20.0%",
        decision_readiness="RESEARCH_ONLY",
    )

    assert result["accountAdvice"] == "建议减仓"
    assert result["suggestedAmount"] == "建议减仓约3,000.00 元"
    assert "策略明确为减仓" in result["reason"]


def test_zero_planned_capital_blocks_weight_calculation() -> None:
    result = evaluate_manual_account(
        account=ManualAccountInput(holding_quantity=100, average_cost=9.0),
        latest_price=10,
        final_signal="BUY_CANDIDATE",
        grade="A",
        target_position_limit="10.0%",
    )

    assert result["accountAdvice"] == "补全账户数据"
    assert "计划总资金" in result["reason"]


def test_payload_parser_ignores_empty_cash_and_normalizes_risk() -> None:
    account = manual_account_from_payload(
        {
            "plannedCapital": "10000",
            "availableCash": "",
            "holdingQuantity": "123.9",
            "averageCost": "2.35",
            "riskProfile": "unknown",
        }
    )

    assert account is not None
    assert account.planned_capital == 10_000
    assert account.available_cash is None
    assert account.holding_quantity == 123
    assert account.average_cost == 2.35
    assert account.risk_profile == "standard"


def test_risk_profile_does_not_change_current_strategy_target() -> None:
    result = evaluate_manual_account(
        account=ManualAccountInput(
            planned_capital=10_000,
            available_cash=10_000,
            risk_profile="aggressive",
        ),
        latest_price=2.0,
        final_signal="BUY_CANDIDATE",
        grade="C",
        target_position_limit="5.0%",
    )

    assert result["targetWeight"] == "5.0%"
    assert result["suggestedAmount"] == "可操作约500.00 元"
    assert "当前策略" in result["reason"]
