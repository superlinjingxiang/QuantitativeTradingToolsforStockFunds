"""Manual account input assessment for the desktop research UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_BUY_SIGNALS = {"BUY_CANDIDATE", "ADD_CANDIDATE", "HOLD"}
_REDUCE_SIGNALS = {"SELL", "REDUCE"}


@dataclass(frozen=True, slots=True)
class ManualAccountInput:
    planned_capital: float = 0.0
    available_cash: float | None = None
    holding_quantity: int = 0
    average_cost: float = 0.0
    risk_profile: str = "standard"


def manual_account_from_payload(payload: object) -> ManualAccountInput | None:
    """Parse the Electron account context payload."""

    if not isinstance(payload, dict) or not payload:
        return None
    return ManualAccountInput(
        planned_capital=_float(payload.get("plannedCapital")),
        available_cash=_optional_float(payload.get("availableCash")),
        holding_quantity=max(0, int(_float(payload.get("holdingQuantity")))),
        average_cost=_float(payload.get("averageCost")),
        risk_profile=_risk_profile(payload.get("riskProfile")),
    )


def evaluate_manual_account(
    *,
    account: ManualAccountInput | None,
    latest_price: float,
    final_signal: str | None,
    grade: str | None,
    target_position_limit: object,
    expected_drawdown: object = None,
    strategy_signal: str | None = None,
    strategy_target_position_limit: object = None,
    decision_readiness: str | None = None,
    capacity_status: str | None = None,
    capacity_limit: float | None = None,
    trading_system: str | None = None,
) -> dict[str, Any]:
    """Translate the current strategy output into account-position advice.

    This function must not run an independent trading strategy. It only uses
    the existing strategy signal and target position limit, then converts that
    into user-specific amount/share suggestions.
    """

    if account is None:
        return {
            "connected": False,
            "summary": "尚未录入账户数据。点击“账户输入”填写计划资金、成本价和持仓数量。",
            "accountAdvice": "未录入",
            "suggestedAmount": "--",
            "suggestedQuantity": "--",
            "reason": "账户数据仅用于研究建议，不会读取券商账户或执行下单。",
            "disclaimer": "研究建议，不构成真实交易指令。",
        }

    price = max(0.0, latest_price)
    quantity = max(0, account.holding_quantity)
    market_value = price * quantity
    cost_value = account.average_cost * quantity
    unrealized_pnl = market_value - cost_value
    unrealized_return = unrealized_pnl / cost_value if cost_value > 0 else 0.0
    planned_capital = max(0.0, account.planned_capital)
    estimated_cash = (
        account.available_cash
        if account.available_cash is not None
        else max(0.0, planned_capital - market_value)
    )
    net_asset = max(planned_capital, market_value + max(0.0, estimated_cash))
    current_weight = market_value / net_asset if net_asset > 0 else 0.0
    decision_target_weight = _parse_percent(target_position_limit)
    research_target_weight = _parse_percent(
        target_position_limit
        if strategy_target_position_limit is None
        else strategy_target_position_limit
    )
    decision_signal = str(final_signal or "").upper()
    strategy_signal_text = str(strategy_signal or decision_signal).upper()
    grade_text = str(grade or "N").upper()
    capacity_status_text = str(capacity_status or "").upper()
    capacity_limit_value = max(0.0, capacity_limit or 0.0)
    capacity_allows_add = not capacity_status_text or (
        capacity_status_text == "PASS"
        and (capacity_limit_value <= 0 or planned_capital <= capacity_limit_value)
    )

    blockers: list[str] = []
    if planned_capital <= 0:
        blockers.append("计划总资金未填写或为0，无法计算仓位比例。")
    if price <= 0:
        blockers.append("最新价格不可用，无法折算建议金额和份额。")
    if account.average_cost <= 0 and quantity > 0:
        blockers.append("已有持仓但成本价未填写，盈亏只能部分估算。")

    advice = "观察"
    reason = "策略证据不足，暂不建议新增仓位。"
    suggested_amount = 0.0

    if blockers:
        advice = "补全账户数据"
        reason = " ".join(blockers)
    elif quantity == 0:
        if decision_signal in _BUY_SIGNALS and decision_target_weight > 0 and capacity_allows_add:
            max_position_value = net_asset * decision_target_weight
            suggested_amount = min(max_position_value, max(0.0, estimated_cash))
            advice = "可小仓试买" if suggested_amount > 0 else "观察"
            reason = (
                f"当前空仓，当前策略通过最终门禁后信号为{_signal_label(decision_signal)}，"
                f"按可执行仓位上限"
                f"{_pct(decision_target_weight)}折算可买金额；等级{grade_text}仅作证据强弱展示。"
            )
        elif not capacity_allows_add:
            advice = "暂不新开仓"
            reason = _capacity_block_reason(
                capacity_status=capacity_status_text,
                planned_capital=planned_capital,
                capacity_limit=capacity_limit_value,
            )
        else:
            advice = "暂不新开仓"
            reason = (
                f"当前策略信号为{_signal_label(strategy_signal_text)}，最终门禁信号为"
                f"{_signal_label(decision_signal)}，可执行仓位上限"
                f"{_pct(decision_target_weight)}，因此不建议新增仓位。"
            )
    else:
        decision_target_value = net_asset * decision_target_weight
        research_target_value = net_asset * research_target_weight
        if strategy_signal_text in _REDUCE_SIGNALS or decision_signal in _REDUCE_SIGNALS:
            suggested_amount = max(0.0, market_value - research_target_value)
            advice = "建议减仓"
            reason = (
                f"当前策略明确为{_signal_label(strategy_signal_text)}，研究仓位上限"
                f"{_pct(research_target_weight)}，"
                f"账户模块只按该策略目标降低已有仓位；当前仓位约{_pct(current_weight)}。"
            )
        elif decision_signal in {"WATCH", "ABSTAIN"}:
            if research_target_weight > 0 and current_weight > research_target_weight + 0.01:
                suggested_amount = market_value - research_target_value
                advice = "建议减仓"
                reason = (
                    f"最终门禁为{_signal_label(decision_signal)}，不允许新增仓位；当前仓位约"
                    f"{_pct(current_weight)}，仍高于策略研究仓位上限"
                    f"{_pct(research_target_weight)}，因此只建议降低超出部分。"
                )
            else:
                advice = "持有观察"
                reason = (
                    f"最终门禁为{_signal_label(decision_signal)}，当前不允许新增仓位；"
                    f"策略没有给出卖出/减仓信号，因此门禁归零不解释为强制清仓。"
                )
        elif current_weight > decision_target_weight + 0.01:
            suggested_amount = market_value - decision_target_value
            advice = "建议减仓"
            reason = (
                f"当前仓位约{_pct(current_weight)}，高于当前策略仓位上限"
                f"{_pct(decision_target_weight)}。"
            )
        elif (
            decision_signal in _BUY_SIGNALS
            and current_weight < decision_target_weight - 0.01
            and capacity_allows_add
        ):
            suggested_amount = min(
                decision_target_value - market_value,
                max(0.0, estimated_cash),
            )
            advice = "可加仓" if suggested_amount > 0 else "持有"
            reason = (
                f"当前仓位约{_pct(current_weight)}，低于当前策略仓位上限"
                f"{_pct(decision_target_weight)}；最终门禁信号为"
                f"{_signal_label(decision_signal)}。"
            )
        elif not capacity_allows_add and current_weight < decision_target_weight - 0.01:
            advice = "持有观察"
            reason = (
                _capacity_block_reason(
                    capacity_status=capacity_status_text,
                    planned_capital=planned_capital,
                    capacity_limit=capacity_limit_value,
                )
                + " 已有仓位不因此被强制卖出，但暂不建议加仓。"
            )
        else:
            advice = "持有观察"
            reason = (
                f"当前仓位约{_pct(current_weight)}，与当前策略仓位上限"
                f"{_pct(decision_target_weight)}基本匹配；"
                f"最终门禁信号为{_signal_label(decision_signal)}。"
            )

    signed_amount = _signed_amount(advice, suggested_amount)
    suggested_quantity = int(suggested_amount // price) if price > 0 and suggested_amount > 0 else 0
    return {
        "connected": True,
        "plannedCapital": _money(planned_capital),
        "availableCash": _money(max(0.0, estimated_cash)),
        "holdingQuantity": quantity,
        "averageCost": _price(account.average_cost),
        "latestPrice": _price(price),
        "marketValue": _money(market_value),
        "costValue": _money(cost_value),
        "unrealizedPnl": _signed_money(unrealized_pnl),
        "unrealizedReturn": _pct(unrealized_return),
        "currentWeight": _pct(current_weight),
        "targetWeight": _pct(decision_target_weight),
        "strategyTargetWeight": _pct(research_target_weight),
        "strategySignal": strategy_signal_text or "--",
        "decisionSignal": decision_signal or "--",
        "decisionReadiness": str(decision_readiness or "--"),
        "tradingSystem": str(trading_system or "--"),
        "capacityStatus": capacity_status_text or "--",
        "capacityLimit": (_money(capacity_limit_value) if capacity_limit_value > 0 else "--"),
        "accountAdvice": advice,
        "suggestedAmount": signed_amount,
        "suggestedQuantity": f"{suggested_quantity} 股/份" if suggested_quantity else "--",
        "reason": reason,
        "riskProfile": _risk_profile_label(account.risk_profile),
        "summary": (
            f"{advice}：当前市值{_money(market_value)}，浮动盈亏{_signed_money(unrealized_pnl)}"
            f"（{_pct(unrealized_return)}），仓位{_pct(current_weight)}。"
        ),
        "disclaimer": (
            "账户建议由当前策略信号和DecisionHub最终门禁共同折算，不构成真实交易指令；"
            "不会读取券商账户或执行下单。"
        ),
    }


def _float(value: object) -> float:
    try:
        if value is None or value == "":
            return 0.0
        if isinstance(value, (int, float, str)):
            return float(value)
        return 0.0
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    parsed = _float(value)
    return max(0.0, parsed)


def _risk_profile(value: object) -> str:
    text = str(value or "standard").strip().lower()
    return text if text in {"conservative", "standard", "aggressive"} else "standard"


def _risk_profile_label(value: str) -> str:
    return {
        "conservative": "保守",
        "standard": "标准",
        "aggressive": "激进",
    }.get(value, "标准")


def _parse_percent(value: object) -> float:
    if value is None:
        return 0.0
    text = str(value).strip()
    try:
        parsed = float(text[:-1] if text.endswith("%") else text)
    except ValueError:
        return 0.0
    return max(0.0, parsed / 100 if parsed > 1 else parsed)


def _signal_label(value: str) -> str:
    return {
        "BUY_CANDIDATE": "买入候选",
        "ADD_CANDIDATE": "加仓候选",
        "SELL": "卖出",
        "REDUCE": "减仓",
        "HOLD": "持有",
        "WATCH": "观察",
        "ABSTAIN": "暂不交易",
    }.get(value, value or "--")


def _signed_amount(advice: str, value: float) -> str:
    if value <= 0:
        return "--"
    prefix = "建议减仓约" if "减仓" in advice or "止损" in advice else "可操作约"
    return f"{prefix}{_money(value)}"


def _capacity_block_reason(
    *,
    capacity_status: str,
    planned_capital: float,
    capacity_limit: float,
) -> str:
    if capacity_limit > 0 and planned_capital > capacity_limit:
        return (
            f"计划资金{_money(planned_capital)}超过ETF组合按2% ADV目标参与率估算的"
            f"容量{_money(capacity_limit)}，当前策略不允许新增风险暴露。"
        )
    return (
        f"ETF组合容量证据为{capacity_status or 'MISSING'}，尚未通过无前视流动性和"
        "冲击成本门禁，当前策略不允许新增风险暴露。"
    )


def _money(value: float) -> str:
    return f"{value:,.2f} 元"


def _signed_money(value: float) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}{abs(value):,.2f} 元"


def _price(value: float) -> str:
    return f"{value:.3f}"


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"
