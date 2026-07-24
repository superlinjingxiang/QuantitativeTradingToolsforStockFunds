"""End-to-end account-context linkage through the application service."""

from __future__ import annotations

from china_quant_platform.data.fake_provider import DeterministicFakeMarketDataProvider
from china_quant_platform.electron_api import ElectronBackendService


def test_analysis_uses_current_strategy_to_build_position_specific_advice() -> None:
    service = ElectronBackendService(env={})
    service._provider = DeterministicFakeMarketDataProvider()  # noqa: SLF001
    payload = {
        "query": "510300",
        "strategyMode": "short_term",
        "maxTrades": 12,
        "interval": "1d",
        "range": "1m",
        "accountContext": {
            "plannedCapital": 10_000,
            "availableCash": 2_000,
            "holdingQuantity": 30,
            "averageCost": 100,
            "riskProfile": "conservative",
        },
    }

    result = service.analyze(payload)
    account = result["accountAssessment"]

    assert account["connected"] is True
    assert account["strategySignal"] == result["analysis"]["operation"]["final_signal"]
    assert account["decisionSignal"] == result["decision"]["final_signal"]
    assert account["holdingQuantity"] == 30
    assert account["averageCost"] == "100.000"
    assert account["riskProfile"] == "保守"
    assert account["accountAdvice"] != "未录入"
    assert "当前市值" in account["summary"]
    assert "个性化目标" in account["summary"]


def test_analysis_without_financial_fields_keeps_account_disconnected() -> None:
    service = ElectronBackendService(env={})
    service._provider = DeterministicFakeMarketDataProvider()  # noqa: SLF001

    result = service.analyze(
        {
            "query": "510300",
            "strategyMode": "short_term",
            "accountContext": {"riskProfile": "standard"},
        }
    )

    assert result["accountAssessment"]["connected"] is False
    assert result["accountAssessment"]["accountAdvice"] == "未录入"
